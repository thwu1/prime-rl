#pragma once

#include "config.h"

#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <string>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

namespace spsc {

// Protocol header placed at the start of every shared-memory segment.
struct ProtocolHeader {
    uint32_t magic;
    uint16_t major_version;
    uint16_t minor_version;
    uint64_t queue_offset;     // Byte offset from segment start to queue buffer
    uint64_t queue_capacity;   // Usable queue buffer size in bytes
    uint64_t total_size;       // Total mapped segment size
};

// Manages creation, opening, and teardown of file-backed shared memory
// segments that follow the SPSC protocol layout.
class ShmManager {
public:
    // Create a new shared-memory segment and return a pointer to the mapping.
    static void* create(const std::string& path, size_t queue_capacity) {
        size_t total_size = sizeof(ProtocolHeader) + queue_capacity;

        int fd = ::open(path.c_str(), O_CREAT | O_RDWR | O_TRUNC, 0666);
        if (fd < 0) throw std::runtime_error("open failed");

        if (ftruncate(fd, total_size) < 0) {
            ::close(fd);
            throw std::runtime_error("ftruncate failed");
        }

        void* ptr = mmap(nullptr, total_size, PROT_READ | PROT_WRITE,
                         MAP_SHARED, fd, 0);
        ::close(fd);
        if (ptr == MAP_FAILED) throw std::runtime_error("mmap failed");

        // Zero the header region
        auto* header = static_cast<ProtocolHeader*>(ptr);
        std::memset(header, 0, sizeof(ProtocolHeader));

        return ptr;
    }

    // Open an existing shared-memory segment and return a pointer.
    static void* open(const std::string& path) {
        int fd = ::open(path.c_str(), O_RDWR, 0666);
        if (fd < 0) throw std::runtime_error("open failed: " + path);

        struct stat sb;
        if (fstat(fd, &sb) < 0) {
            ::close(fd);
            throw std::runtime_error("fstat failed");
        }

        void* ptr = mmap(nullptr, sb.st_size, PROT_READ | PROT_WRITE,
                         MAP_SHARED, fd, 0);
        ::close(fd);
        if (ptr == MAP_FAILED) throw std::runtime_error("mmap failed");

        return ptr;
    }

    static ProtocolHeader* get_header(void* base) {
        return static_cast<ProtocolHeader*>(base);
    }

    static char* get_queue_buffer(void* base) {
        return static_cast<char*>(base) + sizeof(ProtocolHeader);
    }

    static void destroy(const std::string& path, void* ptr, size_t size) {
        munmap(ptr, size);
        ::unlink(path.c_str());
    }
};

}  // namespace spsc
