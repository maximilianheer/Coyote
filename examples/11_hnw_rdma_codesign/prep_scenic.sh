#!/bin/bash

# Define variables for readability
SOURCE="scenic_infiniband_comms.cpp"
OUTPUT="scenic_comms"
LIB_PATH="/home/hmaximili/cyt_rdma_driver/sw/rdma-core/build/lib"

echo "Step 1: Compiling $SOURCE..."

# Run the compilation command
g++ "$SOURCE" -o "$OUTPUT" \
    -libverbs \
    -lrdmacm \
    -lboost_program_options \
    -lpthread

# Check if compilation was successful
if [ $? -eq 0 ]; then
    echo "Compilation successful: ./$OUTPUT created."
    
    # Step 2: Export the library path
    # Note: This export only lasts for the duration of this script 
    # and any processes it starts.
    export LD_LIBRARY_PATH="/home/hmaximili/cyt_rdma_driver/sw/rdma-core/build/lib:$LD_LIBRARY_PATH"
    echo "LD_LIBRARY_PATH updated."

    # Optional: Run the application immediately
    # ./$OUTPUT
else
    echo "Error: Compilation failed."
    exit 1
fi