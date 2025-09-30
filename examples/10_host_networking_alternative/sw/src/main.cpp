// Includes 
#include <any>
#include <chrono>
#include <thread>
#include <iostream>
#include <boost/program_options.hpp>

#include "cThread.hpp"

// Constants 
#define CLOCK_PERIOD_NS 4
#define DEFAULT_VFPGA_ID 0

#define N_LATENCY_REPS 1
#define N_THROUGHPUT_REPS 64

#define BUFFER_RING_SIZE 1024
#define BUFFER_STRIDE 6144
#define IRQ_COALESCE 128 // In packets

// Registers, corresponding to the AXI CTRL registers defined in the vFPGA
enum class BenchmarkRegisters: uint32_t {
    HOST_NETWORKING_PID_REG = 0,            // PID process ID for the transmission
    HOST_NETWORKING_BUFF_VADDR_REG = 1,     // Virtual address of the buffer for RX
    HOST_NETWORKING_BUFF_STRIDE_REG = 2,    // Stride between two packets in the RX buffer
    HOST_NETWORKING_RING_SIZE_REG = 3,      // Size of the ring buffer in number of packets 
    HOST_NETWORKING_RING_TAIL_REG = 4,      // Tail pointer of the ring buffer (updated by FPGA)
    HOST_NETWORKING_RING_HEAD_REG = 5,      // Head pointer of the ring buffer
    HOST_NETWORKING_IRQ_COALESCE_REG = 6    // IRQ coalescing timer in microseconds
};

// Define the meta-tag as datatpye SW-readout 
typedef struct {
    uint32_t possession_flag; // 1 Bit 
    uint32_t packet_len;      // 28 Bits
    uint32_t rsvd;            // 3 Bits, not relevant   
} meta_tag_decoded_t; 

// Function to decode the meta tag from raw memory 
meta_tag_decoded_t decode_meta_tag(uint32_t raw) {
    meta_tag_decoded_t decoded; 
    decoded.possession_flag = (raw >> 31) & 0x1;
    decoded.packet_len = (raw >> 3) & 0x0FFFFFFF;
    decoded.rsvd = raw & 0x7;
    return decoded;
}

// Main function for the host networking example 
int main(int argc, char *argv[]) {
    
    // Obtain a Coyote thread for handling of the buffers 
    coyote::cThread coyote_thread(DEFAULT_VFPGA_ID, getpid());

    // Allocate two buffers for RX and TX traffic 
    int *rx_mem, *tx_mem;
    uint32_t rx_size = 6144 * 64; 
    rx_mem = (int *) coyote_thread.getMem({coyote::CoyoteAllocType::HPF, rx_size});
    // tx_mem = (int *) coyote_thread.getMem({coyote::CoyoteAllocType::HPF, 4*1024*1024});

    // Exit if memory couldn't be allocated 
    // if (!rx_mem || !tx_mem) { throw std::runtime_error("Could not allocate memory; exiting..."); }

    // Create a scatter-gather entry for the TX-stream for outgoing traffic 
    // coyote::localSg sg; 
    // sg = {.addr = tx_mem, .stream=1}; // It should not be required to set the RX-buffer as it is served automatically by the FPGA 

    // Print the buff address for debugging purposes
    std::cout << "RX Buffer Address: " << std::hex << reinterpret_cast<uint64_t>(rx_mem) << std::dec << std::endl;
    std::cout << "CTID: " << std::hex << coyote_thread.getCtid() << std::endl; 
    
    // Communicate the details of the RX-buffer to the vFPGA via the CTRL register 
    coyote_thread.setCSR(reinterpret_cast<uint64_t>(rx_mem), static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_BUFF_VADDR_REG)); // Set vaddr 
    coyote_thread.setCSR(coyote_thread.getCtid(), static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_PID_REG)); // Set PID
    coyote_thread.setCSR(BUFFER_STRIDE, static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_BUFF_STRIDE_REG)); // Set stride
    coyote_thread.setCSR(BUFFER_RING_SIZE, static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_RING_SIZE_REG)); // Set ring size
    coyote_thread.setCSR(0, static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_RING_HEAD_REG)); // Set head pointer to 0
    coyote_thread.setCSR(IRQ_COALESCE, static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_IRQ_COALESCE_REG)); // Set IRQ coalescing timer

    // Write a potential packet to the TX-buffer and then via a LOCAL_WRITE invoke to the FPGA and onto the Ethernet wire 
    /* for(int i = 0; i < 128; i++) {
        tx_mem[i] = i;
    } */ 

    /* tx_mem[0] = 0x0b350a00; 
    tx_mem[1] = 0x0a009824; 
    tx_mem[2] = 0x28250b35; 
    tx_mem[3] = 0x02450008; 
    tx_mem[4] = 0x00003010; 
    tx_mem[5] = 0x11640040; 
    tx_mem[6] = 0xfd0af55b; 
    tx_mem[7] = 0xfd0a684a; 
    tx_mem[8] = 0x3848644a; 
    tx_mem[9] = 0x1c10b712; 
    tx_mem[10] = 0x000d0000; 
    tx_mem[11] = 0x0000ffff; 
    tx_mem[12] = 0x00000000; 
    tx_mem[13] = 0x001f48cf;
    tx_mem[14] = 0x04d2ea19; 
    tx_mem[15] = 0x00000000; */ 

    // coyote_thread.invoke(coyote::CoyoteOper::LOCAL_READ, sg); 

    // Afterwards: Wait for tail to move to position 4   
    while(coyote_thread.getCSR(static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_RING_TAIL_REG)) < 4) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    std::cout << "Received the confirmation over the AXI CTRL interface." << std::endl; 
 
    // If that has happened, go to the fourth position and poll until the possession flag has switched to FPGA 
    uint32_t meta_raw; 
    memcpy(&meta_raw, rx_mem+3*BUFFER_STRIDE, sizeof(uint32_t));
    meta_tag_decoded_t meta = decode_meta_tag(meta_raw);
    uint32_t iteration_counter = 0;

    while((meta.possession_flag != 1) && (iteration_counter<150)) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
        std::cout << "Raw meta flag #4: " << meta_raw << std::endl; 
        memcpy(&meta_raw, rx_mem+3*BUFFER_STRIDE, sizeof(uint32_t));
        meta = decode_meta_tag(meta_raw);
        std::cout << "Possession Flag: " << meta.possession_flag << std::endl;
        iteration_counter++;
    }

    // Fetch the first 4 packets received from the buffer and print out all the information
    for(int j = 0; j < 4; j++) {
        memcpy(&meta_raw, reinterpret_cast<char*>(rx_mem) + j * BUFFER_STRIDE, sizeof(uint32_t));        
        meta = decode_meta_tag(meta_raw);

        std::cout << "Raw meta flag: " << meta_raw << std::endl; 
        std::cout << "Possession Flag: " << meta.possession_flag << std::endl;
        std::cout << "Packet Length: " << meta.packet_len << std::endl;
        std::cout << "Rsvd: " << meta.rsvd << std::endl;
        printf("\n"); 

        // Now get the actual packet data and print it out:
        uint8_t* buf = reinterpret_cast<uint8_t*>(rx_mem);
        for(int i = 0; i < meta.packet_len; i++) {
            uint8_t byte = buf[4+j*BUFFER_STRIDE+i]; 
            std::cout << std::hex << (int) byte << " ";
        }

        printf("\n");
        printf("\n");
    }

    // Let this thread sleep for 10 secs to allow some packets to pass through 
    std::this_thread::sleep_for(std::chrono::seconds(10));
    std::cout << "The end." << std::endl;
    
    // Invalidate the buffer vaddr to stop transmissions 
    coyote_thread.setCSR(0, static_cast<uint32_t>(BenchmarkRegisters::HOST_NETWORKING_BUFF_VADDR_REG)); // Set vaddr 

    // Return value at the end
    return EXIT_SUCCESS;
}

