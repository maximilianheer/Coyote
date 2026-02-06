// WARNING: Uses absolute IP-addresses of alveo-u55c-08, must be changed in order to run on a different server

// alveo-u55c-03:
// 10.253.74.74 - 184371786
// 10.1.212.173 - 167892141
// MAC: 08:c0:eb:c6:40:ca - 9624682381514

// alveo-u55c-04: 
// 10.253.74.78 - 184371790
// 10.1.212.174 - 167892142

// alveo-u55c-08:
// 10.253.74.94 - 184371806
// 10.1.212.178 - 167892146
// MAC: 08:c0:eb:c6:40:aa - 9624682381482

// alveo-u55c-09:
// 10.253.74.98 - 184371810
// 10.1.212.179 - 167892147
// MAC: b8:59:9f:e8:94:9a - 202695074419866

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string>
#include <errno.h>
#include <sys/queue.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netdb.h>
#include <arpa/inet.h>
#include <byteswap.h>
#include <rdma/rdma_cma.h>
#include <unistd.h>
#include <time.h>
#include <stdbool.h>
#include <boost/program_options.hpp>
#include <string>
#include <iostream>
#include <chrono> 
#include <random>
#include <cstring>
#include <sys/mman.h>


struct ibvQ {
    // Node 
    uint32_t ip_addr; 

    // Queue 
    uint32_t qpn; 
    uint32_t psn;
    uint32_t rkey;

    // Buffer 
    uint64_t *vaddr;
    uint32_t size;

    // Global ID 
    char gid[33]; 

    // Function to print a QP
    void print(const char *name) {

        printf("%s: QPN 0x%06x, PSN 0x%06x, RKEY 0x%06x, VADDR %016lx, SIZE %08x, IP 0x%08x\n",
            name, qpn, psn, rkey, (uint64_t)vaddr, size, ip_addr);
    }
};

uint32_t gidToUint(int idx) {
	return (uint32_t)idx;
}

void uintToGid(int idx, uint32_t ip_addr)  {
	printf("Was not implemented! \n");
}

void print(const char *name) {
	printf("Was not implemented! \n");
}

// Function that takes a string-representation of an IP-address and converts to uint32
uint32_t ipv4ToUint32(const std::string& ip) {
    uint32_t result = 0;
    std::stringstream ss(ip);
    std::string segment;
    int octet;

    for (int i = 0; i < 4; ++i) {
        if (!std::getline(ss, segment, '.')) {
            throw std::invalid_argument("Invalid IPv4 address format");
        }
        octet = std::stoi(segment);
        if (octet < 0 || octet > 255) {
            throw std::out_of_range("IPv4 address octet out of range");
        }
        result = (result << 8) | octet;
    }

    return result;
}

void handshake(int connfd) {
	uint32_t sync_ack = 0;
	if (::read(connfd, &sync_ack, sizeof(uint32_t)) != sizeof(uint32_t)) {
        ::close(connfd);
        throw std::runtime_error("Could not read ack\n");
    }

	if(write(connfd, &sync_ack, sizeof(uint32_t)) != sizeof(uint32_t)) {
		close(connfd);
		throw std::runtime_error("18 - Could not send sync_ack!");
	} else {
		printf("Send sync-ack successfully. \n");
	}
}

const int msgAck = 1;
const int msgNAck = 0; 
const int hugePageSize = (2*1024*1024);

// Default parameters for experimentation 
constexpr auto const defOper = false; // read
constexpr auto const defMinSize = 64; 
constexpr auto const defMaxSize = 64 * 1024; 
constexpr auto const defNRepsThr = 1000;
constexpr auto const defNRepsLat = 100;
constexpr auto const defVerbose = false;
constexpr auto const defNTransactions = 1;

int main(int argc, char *argv[]) 
{
	/////////////////////////////////////////////////////////////////////////////////////////////////////////
    //
    // READ IN OF FUNCTION PARAMETERS 
    //
    /////////////////////////////////////////////////////////////////////////////////////////////////////////

    /* 
     * Reading of input arguments for experiment execution 
     */
    boost::program_options::options_description programDescription("Options:");
    programDescription.add_options()
        ("tcpaddr,t", boost::program_options::value<uint32_t>(), "TCP conn IP")
        ("write,w", boost::program_options::value<bool>(), "Read(0)/Write(1)")
        ("min_size,n", boost::program_options::value<uint32_t>(), "Minimal transfer size")
        ("max_size,x", boost::program_options::value<uint32_t>(), "Maximum transfer size")
        ("reps_thr,r", boost::program_options::value<uint32_t>(), "Number of reps, throughput")
        ("reps_lat,l", boost::program_options::value<uint32_t>(), "Number of reps, latency")
        ("verbose,v", boost::program_options::value<bool>(), "Printout of single messages")
		("number_of_transactions,a", boost::program_options::value<uint32_t>(), "Number of transactions to be executed");

    boost::program_options::variables_map commandLineArgs;
    boost::program_options::store(boost::program_options::parse_command_line(argc, argv, programDescription), commandLineArgs);
    boost::program_options::notify(commandLineArgs);

    // Set the default values for the input-determined parameters to have a fall-back in case input-values didn't work properly 
    int tcp_ip;
    bool oper = defOper;
    uint32_t min_size = defMinSize;
    uint32_t max_size = defMaxSize;
    uint32_t n_reps_thr = defNRepsThr;
    uint32_t n_reps_lat = defNRepsLat;
    bool verbose = defVerbose; 
	uint32_t n_transactions = defNTransactions; 

    // Read the actual arguments from the command line and parse them to variables for further usage 
    if(commandLineArgs.count("tcpaddr") > 0) {
        tcp_ip = commandLineArgs["tcpaddr"].as<uint32_t>();
    } else {
		printf("Provide the TCP/IP address of the server. \n"); 
        return (EXIT_FAILURE);
    }
    if(commandLineArgs.count("write") > 0) oper = commandLineArgs["write"].as<bool>();
    if(commandLineArgs.count("min_size") > 0) min_size = commandLineArgs["min_size"].as<uint32_t>();
    if(commandLineArgs.count("max_size") > 0) max_size = commandLineArgs["max_size"].as<uint32_t>();
    if(commandLineArgs.count("reps_thr") > 0) n_reps_thr = commandLineArgs["reps_thr"].as<uint32_t>();
    if(commandLineArgs.count("reps_lat") > 0) n_reps_lat = commandLineArgs["reps_lat"].as<uint32_t>();
    if(commandLineArgs.count("verbose") > 0) verbose = commandLineArgs["verbose"].as<bool>(); 
	if(commandLineArgs.count("number_of_transactions") > 0) n_transactions = commandLineArgs["number_of_transactions"].as<uint32_t>();

	// Print the read-in parameters for verification 
	printf("TCP-IP: %d \n", tcp_ip);
	printf("Operation: %d \n", oper);
	printf("Min-Size: %d \n", min_size);
	printf("Max-Size: %d \n", max_size);
	printf("Reps-Thr: %d \n", n_reps_thr);
	printf("Reps-Lat: %d \n", n_reps_lat);
	printf("Verbose: %d \n", verbose);
	printf("Number of Transactions: %d \n", n_transactions);	


	///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	//
	// CREATION OF LOCAL ELEMENTS FOR COMMUNICATION 
	//
	///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	// Get device to be opened 
	struct ibv_device **dev_list; 
	dev_list = ibv_get_device_list(NULL);
	if(!dev_list) {
		throw std::runtime_error("1 - Device not found!");
		return -1;
	} else {
        // Iterate over the list of devices and print them out
        for (int i = 0; dev_list[i] != NULL; i++) {
            printf("Found device: %s \n", ibv_get_device_name(dev_list[i]));
        }
	}


	// Communication context 
	struct ibv_context *context; 
	context = ibv_open_device(dev_list[1]);
	if(!context) {
		throw std::runtime_error("2 - Context not created, device couldn't be opened!");
		return -1; 
	} else {
		printf("Opened the following device: %s \n", ibv_get_device_name(context->device));
	}

	// Communication Protection Domain 
	struct ibv_pd *pd; 
	pd = ibv_alloc_pd(context);
	if(!pd) {
		throw std::runtime_error("3 - Protection Domain couldn't be allocated!");
		return -1;
	} else {
		// printf("Allocated the Protection Domain. \n");
	}

    // return 0; 

	// Register Memory Region 
	uint32_t n_pages = (max_size + hugePageSize -1) / hugePageSize;
	// uint64_t *buf = (uint64_t *)calloc(1, n_pages*hugePageSize);
	max_size = 2*1024*1024; 
	// printf("Allocating buffer of size %d bytes. \n", max_size);
    uint64_t *buf = (uint64_t *)mmap(NULL, max_size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_HUGETLB, -1, 0);
	if(buf == NULL) {
		throw std::runtime_error("3.5 - Couldn't obtain a buffer in the required size!");
		return -1; 
	} else {
        memset(buf, 0, max_size);
		// printf("Buffer obtained successfully! \n");
	}
	struct ibv_mr *mr; 
	mr = ibv_reg_mr(pd,  buf, max_size, IBV_ACCESS_LOCAL_WRITE | IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ | IBV_ACCESS_RELAXED_ORDERING);
	if(!mr) {
		throw std::runtime_error("4 - Memory Region couldn't be allocated!");
		return -1;
	} else {
		// printf("Allocated the Memory Region. \n");
	}

    // return 0; 

	// Create completion channel
	struct ibv_comp_channel *comp_channel; 
	comp_channel = ibv_create_comp_channel(context);
	if(!comp_channel) {
		throw std::runtime_error("5 - Completion Channel couldn't be created!");
		return -1;
	} else {
		// printf("Created the Completion Channel. \n");
	}

    // return 0; 

	// Create completion queue 
	struct ibv_cq *comp_queue; 
	comp_queue = ibv_create_cq(context, 100, NULL, comp_channel, 0);
	if(!comp_queue) {
		throw std::runtime_error("6 - Completion Queue couldn't be created! ");
		return -1;
	} else {
		// printf("Created the Completion Queue. \n");
	}

    // return 0; 

	// Create init attributes for the queue pair
	struct ibv_qp_init_attr qp_init_attr; 
	memset(&qp_init_attr, 0, sizeof(qp_init_attr));
	qp_init_attr.send_cq = comp_queue;
	qp_init_attr.recv_cq = comp_queue;
	qp_init_attr.qp_type = IBV_QPT_RC;
	qp_init_attr.cap.max_send_wr = 2048; // 128; 
	qp_init_attr.cap.max_recv_wr = 2048; // 128; 
	qp_init_attr.cap.max_send_sge = 16; // 2; 
	qp_init_attr.cap.max_recv_sge = 16; // 2; 
	// printf("Created the QP Init Attributes. \n");

	// Create Queue Pair 
	struct ibv_qp *qp; 
	qp = ibv_create_qp(pd, &qp_init_attr);

	if(!qp) {
		throw std::runtime_error("7 - Queue Pair couldn't be created!");
		return -1;
	} else {
		// printf("Created a Queue Pair. \n");
	}

	// Set Queue Pair to INIT
	struct ibv_qp_attr attr; 
	memset(&attr, 0 , sizeof(attr));
	attr.qp_state = IBV_QPS_INIT; 
	attr.port_num = 1;
	attr.pkey_index = 0; 
	attr.qp_access_flags = IBV_ACCESS_REMOTE_WRITE | IBV_ACCESS_REMOTE_READ; 
	attr.path_mtu = IBV_MTU_4096; 

	printf("Modifying the Queue Pair to INIT. \n");
	switch(ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_ACCESS_FLAGS | IBV_QP_PKEY_INDEX | IBV_QP_PORT)) {
		case 0: printf("Set the Queue Pair to INIT. \n"); break;
		case -1: throw std::runtime_error("8 - Queue Pair couldn't be set to INIT - unspecified!"); return -1; break; 
		case EINVAL: throw std::runtime_error("8 - Queue Pair couldn't be set to INIT - Invalid Value provided!"); return -1; break; 
		case ENOMEM: throw std::runtime_error("8 - Queue Pair couldn't be set to INIT - not enough resources!"); return -1; break;
		default: throw std::runtime_error("8 - Queue Pair couldn't be set to INIT - don't know why."); return -1; break;
	}


	//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	//
	// CREATION OF TCP-SOCKETS FOR LATER QP-EXCHANGE
	//
	//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	int sockfd = -1, connfd; 
	char recv_buf[1024];
	memset(recv_buf, 0, 1024);
	struct sockaddr_in server; 

	// Create socket and test if operation was successful or not 
	sockfd = socket(AF_INET, SOCK_STREAM, 0);
	if(sockfd == -1) {
		throw std::runtime_error("9 - Socket couldn't be created!");
		return -1; 
	} else {
		// printf("Created socket. \n");
	}

	// Force connect the socket
	int optval = 1; 
	if(setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof(int)) < 0) {
		throw std::runtime_error("9.5 - Couldn't set socket option SO_REUSEADDR!");
		return -1; 
	} else {
		// printf("Set socket option SO_REUSEADDR. \n");
	}

	// Server connection given by Protocol, Address, Port
	server.sin_family = AF_INET; 
	server.sin_addr.s_addr = INADDR_ANY; 
	server.sin_port = htons(18488);
	// server.sin_port = htons(4791);

	// Try to bind the socket to the network interface of server, test if that was successful
	if(bind(sockfd, (struct sockaddr*)&server, sizeof(server)) < 0) {
		throw std::runtime_error("10 - Couldn't bind a socket!");
		return -1;
	} else {
		// printf("Bind to a socket. \n");
	}

	// Try to listen to the port
	if(sockfd < 0) {
		throw std::runtime_error("11 - Could not listen to the port!");
		return -1;
	} else {
		// printf("Listened to the port. \n");
	}

	// Listen to the port 
	listen(sockfd, 1);

	// Accept incoming connection 
	connfd = accept(sockfd, NULL, 0);
	
	if(connfd < 0) {
		throw std::runtime_error("12 - Acceptance of incoming connection failed!");
		return -1;
	} else {
		// printf("Accepted the incoming connection \n");
	}


    ///////////////////////////////////////////////////////////////////////////////////////////////
    //
    // QP-EXCHANGE
    //
    ///////////////////////////////////////////////////////////////////////////////////////////////

    // Read the fid from the remote-side. Not necessarily required for Mellanox, but done for compliance-reasons
	// printf("Received the fid with size %ld \n", read(connfd, recv_buf, sizeof(uint32_t)));

	// Read a queue from the socket connection 
	// printf("Size of the read content: %d \n", read(connfd, recv_buf, sizeof(struct ibvQ)));
	// printf("Size of ibvQ-structur: %ld \n", sizeof(struct ibvQ));
	// printf("Received size: %ld \n", read(connfd, recv_buf, sizeof(struct ibvQ)));
	for (size_t i = 0; i < sizeof(struct ibvQ); ++i) {
    	printf("%02x ", (unsigned char)recv_buf[i]);
	}
	printf("\n");
	if(read(connfd, recv_buf, sizeof(struct ibvQ)) != sizeof(struct ibvQ)) {
		close(connfd);
		throw std::runtime_error("15 - Could not read a remote queue!");
	} else {
		printf("Remote queue was read. \n");
	}

	struct ibvQ *remote_ibvQ;
	remote_ibvQ = (struct ibvQ*)malloc(sizeof(struct ibvQ));
	memcpy(remote_ibvQ, recv_buf, sizeof(struct ibvQ));

	// Build remote gid from the received IP-Address
	uint64_t remote_gid;
	remote_gid = 0x0000FFFF00000000 | (uint64_t)remote_ibvQ->ip_addr;
	// printf("ORed remote GID: %ld \n", remote_gid);
	uint32_t high_part = htonl((uint32_t)(remote_gid >> 32));
	uint32_t low_part = htonl((uint32_t) remote_gid & 0xFFFFFFFF);
	remote_gid = ((uint64_t)(low_part) << 32) | high_part;
	// printf("Transformed remote GID: %ld \n", remote_gid);

	// Printout of the received information 
    // remote_ibvQ->print("Remote"); 

    // Negotiate the Balboa-features based on the requirements received in the remote QP and the local arguments 
    
    // If AES was requested in the arguments, generate a potential random AES-key 
    __uint128_t potential_local_aes_key; 
    static unsigned seed = std::chrono::system_clock::now().time_since_epoch().count();
    std::default_random_engine rand_gen(seed); 
    std::uniform_int_distribution<int> distr(0, std::numeric_limits<std::uint32_t>::max());
    std::uniform_int_distribution<uint64_t> distr_aes(1, std::numeric_limits<std::uint64_t>::max()); 

	// Setting up the local information of the ibvQ to send to the remote side 
	struct ibvQ *local_ibvQ; 
	local_ibvQ = (struct ibvQ*)malloc(sizeof(struct ibvQ));
	local_ibvQ->qpn = qp->qp_num;
	local_ibvQ->rkey = mr->lkey;
	local_ibvQ->vaddr = buf; 
	local_ibvQ->psn = remote_ibvQ->psn; 
	local_ibvQ->size = max_size;
	local_ibvQ->ip_addr = tcp_ip;
	sprintf(local_ibvQ->gid, "%08x%08x%08x%08x", local_ibvQ->ip_addr, local_ibvQ->ip_addr, local_ibvQ->ip_addr, local_ibvQ->ip_addr);


	// Send the local queue to the remote target
	if(write(connfd, local_ibvQ, sizeof(struct ibvQ)) != sizeof(struct ibvQ)) {
		close(connfd);
		throw std::runtime_error("16 - Could not send my local Queue to the remote side!");
		return -1; 
	} else {
		// printf("Local Queue was sent to the remote side. \n");
	}

	// Print the QPs 
	local_ibvQ->print("Local"); 
	remote_ibvQ->print("Remote"); 

	//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	//
	// CREATE THE CONNECTION BETWEEN THE QUEUES  
	//
	/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	// Change queuepair to RTR (ready to receive)
	memset(&attr, 0, sizeof(attr));
	union ibv_gid ibv_gid_variable;
	for(int i = 0; i < 16; i++) {
		ibv_gid_variable.raw[i] = (uint8_t) 0;
	}
	ibv_gid_variable.global.subnet_prefix = (__be64)0;
	// ibv_gid_variable.global.interface_id = (__be64)7082751587679928320;
	ibv_gid_variable.global.interface_id = (__be64)remote_gid;
	attr.qp_state = IBV_QPS_RTR;
	attr.path_mtu = IBV_MTU_4096;
	attr.dest_qp_num = remote_ibvQ->qpn;
	attr.rq_psn = local_ibvQ->psn;
	// attr.sq_psn = remote_ibvQ->psn;
	attr.max_dest_rd_atomic = 16;
	attr.max_rd_atomic = 16; 
	attr.min_rnr_timer = 0;
	attr.ah_attr.dlid = 0; 
	attr.ah_attr.sl = 1;
	attr.ah_attr.static_rate = IBV_RATE_100_GBPS; 
	attr.ah_attr.is_global = 1;
	attr.ah_attr.src_path_bits = 0;
	attr.ah_attr.port_num = 1;
	attr.ah_attr.grh.dgid = ibv_gid_variable;
	attr.ah_attr.grh.flow_label = 0;
	attr.ah_attr.grh.sgid_index = 3;
	attr.ah_attr.grh.hop_limit = 4;
	attr.ah_attr.grh.traffic_class = 0; 


	/*attr.alt_ah_attr.dlid = 0; 
	attr.alt_ah_attr.sl = 0;
	attr.alt_ah_attr.static_rate = 0; 
	attr.alt_ah_attr.is_global = 1;
	attr.alt_ah_attr.src_path_bits = 0;
	attr.alt_ah_attr.port_num = 1;
	attr.alt_ah_attr.grh.dgid = ibv_gid_variable;
	attr.alt_ah_attr.grh.flow_label = 0;
	attr.alt_ah_attr.grh.sgid_index = 3;
	attr.alt_ah_attr.grh.hop_limit = 0xFF;
	attr.alt_ah_attr.grh.traffic_class = 0; 
	attr.alt_pkey_index = 0;
	attr.alt_port_num = 1;
	attr.alt_timeout = 22; */

	union ibv_gid gid; 
	int rc = ibv_query_gid(context, 1, 3, &gid);
	if(rc) {
		throw std::runtime_error("Querying the gid didn't work!");
	} else {
		printf("GID-values: \n");
		printf(" - Subnet prefix: %lld \n", gid.global.subnet_prefix);
		printf(" - Interface ID: %lld \n", gid.global.interface_id);
	}

	// Printout of data sent to the remote side
	// printf("IBV_QP_STATE: %d \n", attr.qp_state);
	// printf("IBV_QP_PATH_MTU: %d \n", attr.path_mtu);
	// printf("IBV_QP_DEST_QPN: %d \n", attr.dest_qp_num);
	// printf("IBV_QP_RQ_PSN: %d \n", attr.rq_psn);
	// printf("IBV_QP_MAX_DEST_RD_ATOMIC: %d \n", attr.max_dest_rd_atomic);
	// printf("IBV_QP_MIN_RNR_TIMER: %d \n", attr.min_rnr_timer);
	// printf("IBV AH ATTR: \n");
	// printf(" - DLID: %d \n", attr.ah_attr.dlid);
	// printf(" - Service Level: %d \n", attr.ah_attr.sl);
	// printf(" - Static Rate: %d \n", attr.ah_attr.static_rate);
	// printf(" - Is Global: %d \n", attr.ah_attr.is_global);
	// printf(" - src_path_bits: %d \n", attr.ah_attr.src_path_bits);
	// printf(" - port number: %d \n", attr.ah_attr.port_num);
	// printf(" - Global Routing Header: \n");
	// // printf(" - - flow_label: %d \n", attr.ah_attr.grh.flow_label);
	// printf(" - - sgid_index: %d \n", attr.ah_attr.grh.sgid_index);
	// printf(" - - hop_limit: %d \n", attr.ah_attr.grh.hop_limit);
	// printf(" - - traffic class: %d \n", attr.ah_attr.grh.traffic_class);
	// printf(" - - Global ID: \n");
	// printf(" - - - - Subnet Prefix: %lld \n", attr.ah_attr.grh.dgid.global.subnet_prefix);
	// printf(" - - - - Interface ID: %lld \n", attr.ah_attr.grh.dgid.global.interface_id);

	printf("Modifying the Queue Pair to RTR. \n");
	errno = ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_AV | IBV_QP_PATH_MTU | IBV_QP_DEST_QPN | IBV_QP_RQ_PSN | IBV_QP_MAX_DEST_RD_ATOMIC | IBV_QP_MIN_RNR_TIMER);
	switch(errno) {
		case 0: printf("Set the Queue Pair to RTR. \n"); break;
		case 61: printf("Returned 61. Not ideal, but for now we continue. \n"); break;
		default: printf("%s \n", strerror(errno)); throw std::runtime_error("17 - IBV QP modification went wrong!\n"); sleep(5); return -1; break;
	}

	// Change queuepair to RTS 
	memset(&attr, 0, sizeof(attr));
	attr.qp_state = IBV_QPS_RTS;
	attr.sq_psn = local_ibvQ->psn;
	attr.timeout = 20; 
	attr.retry_cnt = 12; 
	attr.rnr_retry = 1;
	attr.max_rd_atomic = 16; 
	attr.path_mig_state = IBV_MIG_REARM;
	
	printf("Modifying the Queue Pair to RTS. \n");
	errno = ibv_modify_qp(qp, &attr, IBV_QP_STATE | IBV_QP_SQ_PSN | IBV_QP_TIMEOUT | IBV_QP_RETRY_CNT | IBV_QP_RNR_RETRY | IBV_QP_MAX_QP_RD_ATOMIC | IBV_QP_PATH_MIG_STATE);
	if(errno == 0) {
		printf("Set the Queue Pair to RTS. \n");
	} else {
		printf("%s \n", strerror(errno)); 
		throw std::runtime_error("18 - Setting the QP to RTS didn't work properly.");
	}

	// Cast the RDMA-buffer as array of 64-bit integers for further processing 
	uint32_t *hMem = (uint32_t*)local_ibvQ->vaddr; 

	// Create Scatter-Gather-Element 
	struct ibv_sge sg; 
	memset(&sg, 0, sizeof(sg));
	sg.addr = (uintptr_t)hMem; 
	sg.length = min_size; //local_ibvQ->size;
	// sg.length = 64; 
	sg.lkey = mr->lkey;
	// printf("Local Key of the memory region: %d \n", mr->lkey);

	// Create Work Request
	struct ibv_send_wr wr; 
	memset(&wr, 0, sizeof(wr));
	wr.wr_id = 0; 
	wr.sg_list = &sg; 
	wr.num_sge = 1;
	wr.opcode = IBV_WR_RDMA_WRITE; 
	wr.send_flags = IBV_SEND_SIGNALED;
	wr.wr.rdma.remote_addr = (uintptr_t)remote_ibvQ->vaddr;
	wr.wr.rdma.rkey = remote_ibvQ->rkey; 

	// Print the source and target addresses 
	printf("Local RDMA address: %016lx \n", (uintptr_t)hMem);
	printf("Remote RDMA address: %016lx \n", (uintptr_t)remote_ibvQ->vaddr);

	// Create "Bad Work Request" for failed WRITE operations 
	struct ibv_send_wr *bad_wr; 

	// Experimental CQ Moderation 
	/* struct ibv_modify_cq_attr cq_attr;
	cq_attr.moderate.cq_count = 1;   // Process each WR separately
	cq_attr.moderate.cq_period = 0;  // No delay
	ibv_modify_cq(comp_queue, &cq_attr); */ 

	//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	//
	// ACTUAL RDMA-EXCHANGE  
	//
	/////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	// Creation of the Work Completion Element and Counter for Work Completions 
	struct ibv_wc wc; 
	std::vector<struct ibv_wc> wc_batch(n_transactions);
	int num_comp = 0;

	// Creation of the clock for the time measurement 
	clock_t t; 

	// printf("Reached the RDMA-loop! \n");
	// printf("Length of the SG-Element: %d \n", sg.length);
	// printf("Max-size: %d \n", max_size);

	while(sg.length <= max_size) {

        // Generate the elements required for latency and throughput calculation
        std::vector<double> measured_times; 

		// printf("Beginning \n"); 
		printf("Handshake before RDMA ops... \n");
		handshake(connfd); 

		for(int n_runs = 1; n_runs <= n_reps_lat; n_runs++) {
			memset(hMem, 0, sg.length);

            // Start the timer 
            auto begin_time = std::chrono::high_resolution_clock::now();

			for(int n_transmission = 1; n_transmission <= n_transactions; n_transmission++) {
				printf("Posting RDMA READ Work Request, transmission %d / %d ... \n", n_transmission, n_transactions);
				ibv_post_send(qp, &wr, &bad_wr); 
			} 
			printf("All RDMA Work Requests posted. \n");
			printf("This is it - time to say goodbye!\n"); 
			// sleep(600); 

			num_comp = 0; 
			do{
				num_comp += ibv_poll_cq(comp_queue, 1, wc_batch.data());
				printf("Polled the Completion Queue, current number of completions: %d / %d \n", num_comp, n_transactions);
				sleep(2); 
			} while(num_comp < n_transactions);

			if(num_comp < 0) {
				throw std::runtime_error("24 - Polling for the Completion Queue failed!");
				return -1; 
			} else {
				// printf("Received a work completion element: \n");
			}

			/* if(wc.status != IBV_WC_SUCCESS) {
				throw std::runtime_error("25 - wc.status is not IBV_WC_SUCCESS");
				return -1; 
			} */ 

			for(int i = 0; i < n_transactions; i++) {
				if (wc_batch[i].status != IBV_WC_SUCCESS) {
					throw std::runtime_error("26 - wc_batch.status is not IBV_WC_SUCCESS");
					return -1;
				}
			}

            // End the clock 
            auto end_time = std::chrono::high_resolution_clock::now();

            // Calculate the time difference in nanoseconds and store it in the vector 
            double measured_time = std::chrono::duration_cast<std::chrono::nanoseconds>(end_time - begin_time).count();
			// printf("Measured time (ns): %f \n", measured_time);
            measured_times.emplace_back(measured_time);
		}

        ////////////////////////////////////////////////////////////////////
        //
        // TIME STATISTICS CALCULATION
        //
        ///////////////////////////////////////////////////////////////////

        // Order the measured times in the vector 
        std::sort(measured_times.begin(), measured_times.end());

        // Data cleaning: Remove the largest entry
        if (measured_times.size() > 1) {
            measured_times.pop_back();
        }

		// Data cleaning: Remove the smallest entry
		if (measured_times.size() > 1) {
			measured_times.erase(measured_times.begin());
		}

        // Calculate AVG
        double avg_time = 0; 
        for (const double &t : measured_times) {
            avg_time += t;
        }
        avg_time = avg_time / (double) measured_times.size(); 

        // Get MIN
        double min_time = measured_times[0];

        // Get MAX
        double max_time = measured_times[measured_times.size() - 1];

        // Get percentiles 
        double p1 = measured_times[(measured_times.size()/100)-1];
        double p5 = measured_times[(measured_times.size()/20)-1];
        double p10 = measured_times[(measured_times.size()/10)-1];
        double p25 = measured_times[(measured_times.size()/4)-1];
        double p50 = measured_times[(measured_times.size()/2)-1];
        double p75 = measured_times[(3*measured_times.size()/4)-1];
        double p90 = measured_times[(9*measured_times.size()/10)-1];
        double p95 = measured_times[(19*measured_times.size()/20)-1];
        double p99 = measured_times[(99*measured_times.size()/100)-1];

        // Calculate throughput 
        double avg_throughput = (double)sg.length * (double) n_transactions / (1024*1024*avg_time*1e-9); // in MB/sec
        double min_throughput = (double)sg.length * (double) n_transactions / (1024*1024*max_time*1e-9); // in MB/sec
        double max_throughput = (double)sg.length * (double) n_transactions / (1024*1024*min_time*1e-9); // in MB/sec
        double p1_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p99*1e-9); // in MB/sec
        double p5_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p95*1e-9); // in MB/sec
        double p10_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p90*1e-9); // in MB/sec
        double p25_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p75*1e-9); // in MB/sec
        double p50_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p50*1e-9); // in MB/sec
        double p75_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p25*1e-9); // in MB/sec
        double p90_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p10*1e-9); // in MB/sec
        double p95_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p5*1e-9); // in MB/sec
        double p99_throughput = (double)sg.length * (double) n_transactions / (1024*1024*p1*1e-9); // in MB/sec

        // Print the results 
        printf("--------------------------------------------------------------------------------- \n");
        printf("Transmission Size: %d Bytes \n", sg.length);
        printf("-> Number of Transactions: %d \n", n_transactions);
        printf("-> Number of Runs per Transaction: %d \n", n_reps_lat);
        printf(" \n"); 
        printf("Average latency: %f us \n", (avg_time/1e3));
        printf("Minimum latency: %f us \n", (min_time/1e3));
        printf("Maximum latency: %f us \n", (max_time/1e3));
        printf("Percentiles: \n");
        printf(" - 1%%: %f us \n", (p1/1e3));
        printf(" - 5%%: %f us \n", (p5/1e3));
        printf(" - 10%%: %f us \n", (p10/1e3));
        printf(" - 25%%: %f us \n", (p25/1e3));
        printf(" - 50%%: %f us \n", (p50/1e3));
        printf(" - 75%%: %f us \n", (p75/1e3));
        printf(" - 90%%: %f us \n", (p90/1e3));
        printf(" - 95%%: %f us \n", (p95/1e3));
        printf(" - 99%%: %f us \n", (p99/1e3));
        printf(" \n");
        printf("Average throughput: %f MB/sec \n", avg_throughput);
        printf("Minimum throughput: %f MB/sec \n", min_throughput);
        printf("Maximum throughput: %f MB/sec \n", max_throughput);
        printf("Percentiles: \n");
        printf(" - 1%%: %f MB/sec \n", p1_throughput);
        printf(" - 5%%: %f MB/sec \n", p5_throughput);
        printf(" - 10%%: %f MB/sec \n", p10_throughput);
        printf(" - 25%%: %f MB/sec \n", p25_throughput);
        printf(" - 50%%: %f MB/sec \n", p50_throughput);
        printf(" - 75%%: %f MB/sec \n", p75_throughput);
        printf(" - 90%%: %f MB/sec \n", p90_throughput);
        printf(" - 95%%: %f MB/sec \n", p95_throughput);
        printf(" - 99%%: %f MB/sec \n", p99_throughput);
        printf(" \n");
        printf(" \n");

		sg.length = sg.length * 2;
	}

	printf("End");
	handshake(connfd); 

	///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
	//
	// CLEAN-UP OF ELEMENTS 
	//
	///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

	printf("\n");
	printf("\n");
	printf("############################################################################################# \n");
	printf("This is the end... \n");
	printf(" - Free the buffer now! \n");
	if(buf != NULL) {
		printf("Buffer is not a nullpointer! \n");
		free((void*)*buf);
	} else {
		printf("Couldn't free the buffer! \n");
	}
	printf(" - Destroy the queue pair! \n");
	ibv_destroy_qp(qp);
	printf(" - Destroy the completion queue! \n");
	ibv_destroy_cq(comp_queue);
	printf(" - Destroy the completion channel! \n");
	ibv_destroy_comp_channel(comp_channel);
	printf(" - Dereg the memory region! \n");
	ibv_dereg_mr(mr);
	printf(" - Deallocate the Protection Domain! \n");
	ibv_dealloc_pd(pd);
	printf(" - Close the device! \n");
	ibv_close_device(context);
	printf(" - Close the socket! \n");
	close(connfd);

	return 0;
}