#ifndef SB2_FORMAT_H
#define SB2_FORMAT_H

/*
 *
 * Secure Binary 2 (SB2) Firmware Update Header
 * Based on the NXP SB2 format used in LPC55 microcontrollers.
 * Total size: 128 bytes (8 blocks of 16 bytes each).
 */

#include <stdint.h>

#define SB2_BLOCK_SIZE    16
#define SB2_HEADER_BLOCKS 8
#define SB2_HEADER_SIZE   (SB2_HEADER_BLOCKS * SB2_BLOCK_SIZE) /* 128 */

struct __attribute__((packed)) sb2_header {
    uint32_t nonce[4];                     /* 0x00: Random nonce (16 bytes)       */
    uint32_t reserved;                     /* 0x10: Reserved                      */
    uint8_t  m_signature[4];               /* 0x14: Primary magic  "STMP"         */
    uint8_t  m_majorVersion;               /* 0x18: Major version (must be 2)     */
    uint8_t  m_minorVersion;               /* 0x19: Minor version                 */
    uint16_t m_flags;                      /* 0x1A: Flags                         */
    uint32_t m_imageBlocks;                /* 0x1C: Total image size in blocks    */
    uint32_t m_firstBootTagBlock;          /* 0x20: First boot tag block          */
    uint32_t m_firstBootableSectionID;     /* 0x24: First bootable section ID     */
    uint32_t m_offsetToCertBlockBytes;     /* 0x28: Offset to certificate block   */
    uint16_t m_headerBlocks;               /* 0x2C: Number of header blocks       */
    uint16_t m_keyBlobBlock;               /* 0x2E: Block number of key blob      */
    uint16_t m_keyBlobBlockCount;          /* 0x30: Number of key blob blocks     */
    uint16_t m_maxSectionMacCount;         /* 0x32: Max section MAC count         */
    uint8_t  m_signature2[4];              /* 0x34: Secondary magic "sgtl"        */
    uint64_t m_timestamp;                  /* 0x38: Build timestamp               */
    uint32_t m_productVersion[4];          /* 0x40: Product version               */
    uint32_t m_componentVersion[4];        /* 0x50: Component version             */
    uint32_t m_buildNumber;                /* 0x60: Build number                  */
    uint8_t  m_padding1[4];               /* 0x64: Padding                       */
    uint8_t  m_digest[20];                /* 0x68: SHA-1 digest of image data    */
    uint8_t  m_padding2[4];               /* 0x7C: Final padding                 */
};

_Static_assert(sizeof(struct sb2_header) == SB2_HEADER_SIZE,
               "sb2_header must be exactly 128 bytes");

#endif /* SB2_FORMAT_H */
