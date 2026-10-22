import ctypes,math
from pathlib import Path
import numpy as np

class RawCoyoteOverlay:
    def open_production_session(self, max_input_bytes=134217664):
        """Reuse the production LOCAL_TRANSFER context and buffers across inputs."""
        from production_session import ProductionCoyoteSession
        return ProductionCoyoteSession(self, max_input_bytes)

    def __init__(self, path: str | Path, project_name: str = "myproject") -> None:
        self.path = Path(path).resolve()
        self.project_name = project_name
        self.lib_path = self.path / "build" / f"{self.project_name}_cyt_sw" / "lib" / "libCoyoteInference.so"
        if not self.lib_path.exists():
            raise FileNotFoundError(self.lib_path)
        self.coyote_lib = ctypes.cdll.LoadLibrary(str(self.lib_path))
        self._bind_common_symbols()
        self._bind_raw_symbols()

    def _bind_common_symbols(self) -> None:
        model_ptr = ctypes.POINTER(ctypes.c_void_p)
        self.coyote_lib.flush.argtypes = [model_ptr]
        self.coyote_lib.predict.argtypes = [model_ptr]
        self.coyote_lib.get_inference_predictions.argtypes = [model_ptr, ctypes.c_uint]
        self.coyote_lib.get_inference_predictions.restype = ctypes.POINTER(ctypes.c_float)
        self.coyote_lib.free_model_inference.argtypes = [model_ptr]

    def _bind_raw_symbols(self) -> None:
        model_ptr = ctypes.POINTER(ctypes.c_void_p)
        self.coyote_lib.init_model_inference_raw.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint]
        self.coyote_lib.init_model_inference_raw.restype = model_ptr

        np_pointer_u8 = np.ctypeslib.ndpointer(dtype=np.uint8, ndim=1, flags="C")
        self.coyote_lib.set_inference_raw_data.argtypes = [model_ptr, np_pointer_u8, ctypes.c_uint, ctypes.c_uint]

    @staticmethod
    def _free_hugepages_2m() -> int | None:
        path = Path("/sys/kernel/mm/hugepages/hugepages-2048kB/free_hugepages")
        try:
            return int(path.read_text().strip())
        except OSError:
            return None

    @staticmethod
    def _required_hugepages_2m(batch_size: int, max_input_bytes: int, out_items: int) -> int:
        page_bytes = 2 * 1024 * 1024
        raw_pages = math.ceil((64 + max_input_bytes) / page_bytes)
        out_pages = math.ceil((out_items * np.dtype(np.float32).itemsize) / page_bytes)
        return batch_size * (raw_pages + out_pages)

