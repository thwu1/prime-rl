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

struct ProtocolHeader {
    uint32_t magic;
    uint16_t major_version;
    uint16_t minor_version;
    uint64_t queue_offset;
    uint64_t queue_capacity;
    uint64_t total_size;
};

class ShmManager {
public:
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

        // Properly initialize the protocol header.
        auto* header = static_cast<ProtocolHeader*>(ptr);
        header->magic          = kProtocolMagic;
        header->major_version  = kMajorVersion;
        header->minor_version  = kMinorVersion;
        header->queue_offset   = sizeof(ProtocolHeader);
        header->queue_capacity = queue_capacity;
        header->total_size     = total_size;

        return ptr;
    }

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

        // Validate the protocol header.
        auto* header = static_cast<ProtocolHeader*>(ptr);
        if (header->magic != kProtocolMagic) {
            munmap(ptr, sb.st_size);
            throw std::runtime_error("invalid magic number");
        }
        if (header->major_version != kMajorVersion) {
            munmap(ptr, sb.st_size);
            throw std::runtime_error("incompatible major version");
        }

        return ptr;
    }

    static ProtocolHeader* get_header(void* base) {
        return static_cast<ProtocolHeader*>(base);
    }

    static char* get_queue_buffer(void* base) {
        auto* header = get_header(base);
        return static_cast<char*>(base) + header->queue_offset;
    }

    static void destroy(const std::string& path, void* ptr, size_t size) {
        munmap(ptr, size);
        ::unlink(path.c_str());
    }
};

}  // namespace spsc
