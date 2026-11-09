// Allocation, HBM placement, CSR timing and DLPack transport. TensorFlow runs
// the original FP32 model; no inference backend is implemented here.
#include "mailbox.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <chrono>
#include <cstring>
#include <functional>
#include <memory>
#include <string>

namespace py = pybind11;
struct DLDevice { int device_type, device_id; };
struct DLDataType { uint8_t code, bits; uint16_t lanes; };
struct DLTensor {
    void* data; DLDevice device; int ndim; DLDataType dtype;
    int64_t* shape; int64_t* strides; uint64_t byte_offset;
};
struct DLManagedTensor {
    DLTensor dl_tensor; void* manager_ctx; void (*deleter)(DLManagedTensor*);
};
static uint64_t now_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}

class HbmTransport : public std::enable_shared_from_this<HbmTransport> {
    std::unique_ptr<GpuThread> thread;
    unsigned char* host = nullptr;
    unsigned char* gpu = nullptr;
    unsigned long long* box = nullptr;
    hipStream_t stream = nullptr;
    uint32_t capacity, length = 0;
    unsigned variant;
    uint64_t trial = 0, started = 0, ready_seen = 0;
    bool armed = false;

    void wait_for(const std::function<bool()>& predicate) {
        while (!predicate()) {
            if (thread->getCSR(0) & 4)
                throw std::runtime_error("HBM error; retain mappings and reset safely");
            if (now_ns() - started > 31000000000ULL)
                throw std::runtime_error("HBM timeout; retain mappings and reset safely");
        }
    }

public:
    explicit HbmTransport(uint32_t bytes) : capacity(bytes) {
        if (!capacity || capacity > 134217728 || capacity % 2097152)
            throw std::runtime_error("capacity must be hugepage aligned and <=128MiB");
        thread = std::make_unique<GpuThread>();
        const uint64_t signature = thread->getCSR(4);
        variant = signature & 0xffff;
        const bool control = (signature & ~65535ULL) == 0x4342595400050000ULL &&
                             (variant == 10 || variant == 11);
        const bool reader = (signature & ~65535ULL) == 0x4342595400060000ULL &&
                            (variant >= 14 && variant <= 16);
        if (!control && !reader)
            throw std::runtime_error("Requires supported HBM ABI5 control or ABI6 reader");
        host = static_cast<unsigned char*>(thread->getMem({coyote::CoyoteAllocType::HPF, capacity}));
        if (!host) throw std::runtime_error("HPF allocation failed");
        if (variant == 11) {
            hip_check(hipSetDevice(0));
            char gpu_bus[32] = {};
            hip_check(hipDeviceGetPCIBusId(gpu_bus, sizeof(gpu_bus), 0));
            if (std::string(gpu_bus) != "0000:03:00.0")
                throw std::runtime_error("GPU0 is not the reserved MI210 at 03:00.0");
            gpu = static_cast<unsigned char*>(thread->fine_alloc(capacity));
            box = static_cast<unsigned long long*>(thread->fine_alloc(4096));
            hip_check(hipStreamCreateWithFlags(&stream, hipStreamNonBlocking));
        }
    }

    ~HbmTransport() {
        if (!thread) return;
        if (thread->getCSR(0) & 1) {
            // Unmapping a live device transaction is unsafe. Controller recovery
            // resets/quiesces hardware before the operating system reclaims it.
            thread.release();
            return;
        }
        if (stream) hipStreamDestroy(stream);
    }

    void offload() {
        coyote::syncSg placement = {.addr = host, .len = capacity};
        thread->invoke(coyote::CoyoteOper::LOCAL_OFFLOAD, placement);
    }

    void load(py::array_t<uint8_t, py::array::c_style> raw) {
        if (armed || raw.size() > capacity - 64)
            throw std::runtime_error("Invalid load or live frame");
        length = raw.size();
        std::memset(host, 0, capacity);
        if (length) std::memcpy(host, raw.data(), length);
        offload();
        if (variant == 11) {
            unsigned char header[64] = {};
            uint64_t value = length;
            std::memcpy(header, &value, sizeof(value));
            hip_check(hipMemcpy(gpu, header, 64, hipMemcpyHostToDevice));
        }
    }

    bool verify(py::array_t<uint8_t, py::array::c_style> expected) {
        if (armed || expected.size() != length) throw std::runtime_error("Invalid verification");
        // Poison the host mirror so this verifies the actual HBM-to-host copy.
        if (length) std::memset(host, 0xa7, length);
        coyote::syncSg transfer = {.addr = host, .len = capacity};
        thread->invoke(coyote::CoyoteOper::LOCAL_SYNC, transfer);
        const bool matches = !length || std::memcmp(host, expected.data(), length) == 0;
        if (!matches) throw std::runtime_error("HBM readback differs from raw input");
        // LOCAL_SYNC remaps pages to HOST_ACCESS. Restore card residency now,
        // outside timing, rather than accepting a page migration in the trial.
        offload();
        return true;
    }

    void start(uint64_t identifier, uint64_t setting = 0) {
        if (armed || !identifier || !(identifier & 0xffffffffULL) || (thread->getCSR(0) & 1))
            throw std::runtime_error("Invalid trial/rearm");
        if (variant == 11) {
            hip_check(hipMemsetAsync(box, 0, 128, stream));
            hip_check(hipStreamSynchronize(stream));
        }
        trial = identifier;
        thread->setCSR(setting, 14);
        thread->setCSR(length, 1);
        thread->setCSR(trial, 2);
        thread->setCSR(thread->getCtid(), 3);
        thread->setCSR(uint64_t(host), 8);
        if (variant == 11) {
            thread->setCSR(uint64_t(gpu), 9);
            thread->setCSR(uint64_t(box), 10);
            thread->setCSR(uint64_t(box + 8), 11);
        }
        thread->setCSR(7500000000ULL, 12);
        thread->setCSR(250, 13);
        const auto previous_arm = thread->getCSR(6);
        started = now_ns();
        thread->setCSR(1, 0);
        armed = true;
        // Reject stale completion counters when consecutive trials reuse a size.
        wait_for([&] { return thread->getCSR(6) != previous_arm; });
    }

    void wait_input() {
        if (variant != 11) throw std::runtime_error("GPU-only readiness wait");
        wait_for([&] { return thread->getCSR(48) == length &&
            thread->getCSR(49) == (uint64_t(length) + 65535) / 65536; });
        hip_check(hipDeviceSynchronize());
        ready_seen = now_ns();
    }

    py::capsule input_capsule() {
        if (variant != 11) throw std::runtime_error("GPU-only input");
        auto* tensor = new DLManagedTensor{};
        tensor->dl_tensor = {gpu + 64, {10, 0}, 1, {1, 8, 1},
                            new int64_t[1]{length}, nullptr, 0};
        tensor->manager_ctx = new std::shared_ptr<HbmTransport>(shared_from_this());
        tensor->deleter = [](DLManagedTensor* value) {
            delete[] value->dl_tensor.shape;
            delete static_cast<std::shared_ptr<HbmTransport>*>(value->manager_ctx);
            delete value;
        };
        return py::capsule(tensor, "dltensor", [](PyObject* object) {
            if (PyCapsule_IsValid(object, "dltensor")) {
                auto* value = static_cast<DLManagedTensor*>(PyCapsule_GetPointer(object, "dltensor"));
                value->deleter(value);
            }
        });
    }

    void publish(py::capsule capsule, uint64_t generation = 0) {
        auto* tensor = static_cast<DLManagedTensor*>(PyCapsule_GetPointer(capsule.ptr(), "dltensor"));
        if (!tensor) throw py::error_already_set();
        auto& data = tensor->dl_tensor;
        uint64_t elements = 1;
        for (int i = 0; i < data.ndim; ++i) elements *= data.shape[i];
        if (data.device.device_type != 10 || data.device.device_id != 0 ||
            data.dtype.bits != 32 || data.dtype.code != 2 || elements != 1)
            throw std::runtime_error("Expected scalar FP32 GPU0 result");
        const auto* score = reinterpret_cast<const float*>(static_cast<char*>(data.data) + data.byte_offset);
        const auto publication_trial = generation ? generation : trial;
        hipLaunchKernelGGL(publish_mailbox, dim3(1), dim3(1), 0, stream, box, score, publication_trial, 0x43565234U);
        hip_check(hipGetLastError());
        hip_check(hipStreamSynchronize(stream));
        PyCapsule_SetName(capsule.ptr(), "used_dltensor");
        if (tensor->deleter) tensor->deleter(tensor);
    }

    py::dict finish() {
        wait_for([&] { return thread->getCSR(0) & 8; });
        const auto observed = now_ns();
        wait_for([&] { return (thread->getCSR(0) & 7) == 2; });
        py::dict result;
        result["host_start_ns"] = started;
        result["host_verdict_seen_ns"] = observed;
        result["host_drained_ns"] = now_ns();
        result["gpu_input_ready_ns"] = ready_seen;
        for (unsigned i = 0; i < 64; ++i)
            result[py::str("csr_" + std::to_string(i))] = thread->getCSR(i);
        armed = false;
        return result;
    }

    py::list calibrate() {
        py::list result;
        for (int i = 0; i < 32; ++i) {
            auto before = now_ns();
            auto tick = thread->getCSR(5);
            auto after = now_ns();
            result.append(py::make_tuple(before, tick, after));
        }
        return result;
    }

    py::dict snapshot() {
        py::dict result;
        for (unsigned i = 0; i < 64; ++i)
            result[py::str("csr_" + std::to_string(i))] = thread->getCSR(i);
        return result;
    }

    py::array_t<uint8_t> read_gpu() {
        if (variant != 11) throw std::runtime_error("GPU-only readback");
        py::array_t<uint8_t> result(length);
        if (length) hip_check(hipMemcpy(result.mutable_data(), gpu + 64, length, hipMemcpyDeviceToHost));
        return result;
    }
};

PYBIND11_MODULE(hbm_transport, module) {
    py::class_<HbmTransport, std::shared_ptr<HbmTransport>>(module, "Transport")
        .def(py::init<uint32_t>())
        .def("load", &HbmTransport::load)
        .def("verify", &HbmTransport::verify)
        .def("start", &HbmTransport::start, py::arg("identifier"), py::arg("setting") = 0)
        .def("wait_input", &HbmTransport::wait_input)
        .def("input_capsule", &HbmTransport::input_capsule)
        .def("publish", &HbmTransport::publish, py::arg("capsule"), py::arg("generation") = 0)
        .def("finish", &HbmTransport::finish)
        .def("snapshot", &HbmTransport::snapshot)
        .def("read_gpu", &HbmTransport::read_gpu)
        .def("calibrate", &HbmTransport::calibrate);
}
