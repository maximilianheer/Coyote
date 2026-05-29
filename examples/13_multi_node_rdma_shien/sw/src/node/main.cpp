/**
 * This file is part of the Coyote <https://github.com/fpgasystems/Coyote>
 *
 * MIT Licence
 * Copyright (c) 2021-2025, Systems Group, ETH Zurich
 * All rights reserved.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:

 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.

 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

/**
 * Multi-node pairwise RDMA QP setup.
 *
 * Each node establishes one QP to every other node, giving n*(n-1)/2 QPs total
 * across the cluster (2 <= n <= 10).  No RDMA transfers are performed here;
 * RDMA will be driven from HW later.
 *
 * Usage (example for 3 nodes):
 *   node0$ ./test -n 3 -d 0 -a 10.0.0.0,10.0.0.1,10.0.0.2
 *   node1$ ./test -n 3 -d 1 -a 10.0.0.0,10.0.0.1,10.0.0.2
 *   node2$ ./test -n 3 -d 2 -a 10.0.0.0,10.0.0.1,10.0.0.2
 *
 * Port assignment: pair (low_id, high_id) uses TCP port BASE_PORT + low_id * N_MAX_NODES + high_id.
 * The node with the lower ID acts as the TCP server for that pair.
 */

#include <iostream>
#include <string>
#include <sstream>
#include <vector>
#include <thread>
#include <memory>
#include <stdexcept>
#include <chrono>
#include <cassert>

#include <boost/program_options.hpp>

#include <coyote/cThread.hpp>
#include <constants.hpp>

namespace po = boost::program_options;

// Returns the TCP port used for the OOB QP exchange of pair (low_id, high_id).
static uint16_t pair_port(unsigned int low_id, unsigned int high_id) {
    return static_cast<uint16_t>(BASE_PORT + low_id * N_MAX_NODES + high_id);
}

// Splits a comma-separated string of IPs into a vector.
static std::vector<std::string> split_ips(const std::string &s) {
    std::vector<std::string> result;
    std::stringstream ss(s);
    std::string token;
    while (std::getline(ss, token, ',')) {
        if (!token.empty()) result.push_back(token);
    }
    return result;
}

// Calls initRDMA as a client, retrying on connection failure until the server
// is ready.  Throws after max_retries consecutive failures.
static void* initRDMAClientWithRetry(
    coyote::cThread &thread, uint64_t buf_size, uint16_t port,
    const std::string &server_ip, int max_retries = 30, int retry_ms = 1000
) {
    for (int attempt = 0; attempt < max_retries; attempt++) {
        try {
            return thread.initRDMA(buf_size, port, server_ip.c_str());
        } catch (const std::exception &e) {
            if (attempt + 1 < max_retries) {
                std::cerr << "[node] connect to " << server_ip << ":" << port
                          << " failed, retry " << (attempt + 1) << "/" << max_retries
                          << " (" << e.what() << ")" << std::endl;
                std::this_thread::sleep_for(std::chrono::milliseconds(retry_ms));
            } else {
                throw;
            }
        }
    }
    return nullptr; // unreachable
}

int main(int argc, char *argv[]) {
    unsigned int n_nodes, node_id;
    std::string node_ips_str;
    uint64_t buffer_size;

    po::options_description opts("Multi-node RDMA QP Setup Options");
    opts.add_options()
        ("help,h", "Print this help message")
        ("n_nodes,n", po::value<unsigned int>(&n_nodes)->required(),
            "Total number of nodes (2-10)")
        ("node_id,d", po::value<unsigned int>(&node_id)->required(),
            "This node's ID (0-indexed, must be < n_nodes)")
        ("node_ips,a", po::value<std::string>(&node_ips_str)->required(),
            "Comma-separated IP addresses of all nodes in node-ID order")
        ("buffer_size,s", po::value<uint64_t>(&buffer_size)->default_value(DEFAULT_BUFFER_SIZE),
            "Per-QP RDMA buffer size in bytes");

    po::variables_map vm;
    try {
        po::store(po::parse_command_line(argc, argv, opts), vm);
        if (vm.count("help")) { std::cout << opts << std::endl; return EXIT_SUCCESS; }
        po::notify(vm);
    } catch (const po::error &e) {
        std::cerr << "ERROR: " << e.what() << std::endl << opts << std::endl;
        return EXIT_FAILURE;
    }

    if (n_nodes < 2 || n_nodes > N_MAX_NODES) {
        std::cerr << "ERROR: n_nodes must be between 2 and " << N_MAX_NODES << std::endl;
        return EXIT_FAILURE;
    }
    if (node_id >= n_nodes) {
        std::cerr << "ERROR: node_id must be < n_nodes (" << n_nodes << ")" << std::endl;
        return EXIT_FAILURE;
    }

    std::vector<std::string> node_ips = split_ips(node_ips_str);
    if (node_ips.size() != n_nodes) {
        std::cerr << "ERROR: number of IPs (" << node_ips.size()
                  << ") does not match n_nodes (" << n_nodes << ")" << std::endl;
        return EXIT_FAILURE;
    }

    unsigned int n_peers = n_nodes - 1;
    unsigned int n_pairs = n_nodes * (n_nodes - 1) / 2;

    HEADER("CLI PARAMETERS:");
    std::cout << "Node ID         : " << node_id << std::endl;
    std::cout << "Total nodes     : " << n_nodes << std::endl;
    std::cout << "Total QP pairs  : " << n_pairs << std::endl;
    std::cout << "Buffer size     : " << buffer_size << " bytes" << std::endl;
    std::cout << "Node IPs        :";
    for (unsigned int i = 0; i < n_nodes; i++) {
        std::cout << "  [" << i << "] " << node_ips[i];
    }
    std::cout << std::endl << std::endl;

    // One cThread per peer.  Index mapping: peer_ids 0..n_nodes-1 (skipping node_id)
    // are mapped to thread indices 0..n_peers-1.
    auto peer_to_idx = [&](unsigned int peer_id) -> unsigned int {
        return peer_id < node_id ? peer_id : peer_id - 1;
    };

    std::vector<std::unique_ptr<coyote::cThread>> cthreads(n_peers);
    for (unsigned int peer_id = 0; peer_id < n_nodes; peer_id++) {
        if (peer_id == node_id) continue;
        cthreads[peer_to_idx(peer_id)] = std::make_unique<coyote::cThread>(DEFAULT_VFPGA_ID, getpid());
    }

    std::vector<void *> mems(n_peers, nullptr);
    std::vector<std::exception_ptr> server_errors(n_peers, nullptr);

    // Phase 1: launch server threads for peers with higher ID (this node listens).
    std::vector<std::thread> server_threads;
    for (unsigned int peer_id = node_id + 1; peer_id < n_nodes; peer_id++) {
        unsigned int idx = peer_to_idx(peer_id);
        uint16_t port = pair_port(node_id, peer_id);
        std::cout << "[node " << node_id << "] listening for peer " << peer_id
                  << " on port " << port << std::endl;
        server_threads.emplace_back([&, idx, port]() {
            try {
                mems[idx] = cthreads[idx]->initRDMA(buffer_size, port);
            } catch (...) {
                server_errors[idx] = std::current_exception();
            }
        });
    }

    // Phase 2: connect as client to peers with lower ID (they are the servers).
    // Retry until the remote server is ready.
    for (unsigned int peer_id = 0; peer_id < node_id; peer_id++) {
        unsigned int idx = peer_to_idx(peer_id);
        uint16_t port = pair_port(peer_id, node_id);
        std::cout << "[node " << node_id << "] connecting to peer " << peer_id
                  << " at " << node_ips[peer_id] << ":" << port << std::endl;
        try {
            mems[idx] = initRDMAClientWithRetry(*cthreads[idx], buffer_size, port, node_ips[peer_id]);
        } catch (const std::exception &e) {
            std::cerr << "ERROR: failed to connect to peer " << peer_id << ": " << e.what() << std::endl;
            // Join any running server threads before exiting.
            for (auto &t : server_threads) { if (t.joinable()) t.join(); }
            return EXIT_FAILURE;
        }
    }

    // Phase 3: wait for all server threads to complete.
    for (auto &t : server_threads) { t.join(); }

    // Check for errors in server threads.
    for (unsigned int peer_id = node_id + 1; peer_id < n_nodes; peer_id++) {
        unsigned int idx = peer_to_idx(peer_id);
        if (server_errors[idx]) {
            try {
                std::rethrow_exception(server_errors[idx]);
            } catch (const std::exception &e) {
                std::cerr << "ERROR: QP setup with peer " << peer_id << " failed: " << e.what() << std::endl;
                return EXIT_FAILURE;
            }
        }
    }

    // Phase 4: write QP information into the vFPGA control registers so that HW can
    // issue RDMA requests directly.
    //
    // Register layout in shien_rdma_qp_ctrl_parser (indexed by peer node ID, not
    // the internal peer index, so HW can address them with a simple node-ID mux):
    //   CSR offset  3*peer_id + 0  : local QPN (24-bit)
    //   CSR offset  3*peer_id + 1  : remote vaddr (buffer address on the peer)
    //   CSR offset  3*peer_id + 2  : local  vaddr (buffer address on this node)
    //
    // All cThreads share the same ctrl_reg space (same vFPGA), so any cThread
    // instance can be used for the write; we use the per-peer one for clarity.
    HEADER("WRITING QP INFO TO HW REGISTERS:");
    for (unsigned int peer_id = 0; peer_id < n_nodes; peer_id++) {
        if (peer_id == node_id) continue;
        unsigned int idx = peer_to_idx(peer_id);
        coyote::cThread &ct = *cthreads[idx];
        coyote::ibvQp *qp = ct.getQpair();

        uint64_t qpn    = static_cast<uint64_t>(qp->local.qpn);
        uint64_t rvaddr = reinterpret_cast<uint64_t>(qp->remote.vaddr);
        uint64_t lvaddr = reinterpret_cast<uint64_t>(qp->local.vaddr);

        ct.setCSR(qpn,    3 * peer_id + 0);
        ct.setCSR(rvaddr, 3 * peer_id + 1);
        ct.setCSR(lvaddr, 3 * peer_id + 2);

        std::cout << "  peer " << peer_id
                  << ": QPN=0x" << std::hex << qpn
                  << "  rvaddr=0x" << rvaddr
                  << "  lvaddr=0x" << lvaddr
                  << std::dec << std::endl;
    }

    // Signal to HW that all QP information is valid and RDMA can proceed.
    // Any cThread on this vFPGA can write the done flag; use the first peer's thread.
    cthreads[0]->setCSR(1, 3 * N_MAX_NODES);
    std::cout << "  qp_setup_done written to HW (CSR offset " << 3 * N_MAX_NODES << ")" << std::endl;

    // Release the OOB TCP connections (no longer needed after QP exchange).
    for (unsigned int peer_id = 0; peer_id < n_nodes; peer_id++) {
        if (peer_id == node_id) continue;
        cthreads[peer_to_idx(peer_id)]->closeConn();
    }

    HEADER("QP SETUP COMPLETE");
    std::cout << "Node " << node_id << " has established QPs with all " << n_peers << " peer(s):" << std::endl;
    for (unsigned int peer_id = 0; peer_id < n_nodes; peer_id++) {
        if (peer_id == node_id) continue;
        unsigned int idx = peer_to_idx(peer_id);
        std::cout << "  peer " << peer_id << " (" << node_ips[peer_id] << "): buffer @ " << mems[idx] << std::endl;
    }

    return EXIT_SUCCESS;
}
