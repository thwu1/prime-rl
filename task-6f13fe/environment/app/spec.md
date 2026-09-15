LZ4 Block Format Description
============================
Last revised: 2022-07-31 .
Author : Yann Collet


This specification is intended for developers willing to
produce or read LZ4 compressed data blocks
using any programming language of their choice.

LZ4 is an LZ77-type compressor with a fixed byte-oriented encoding format.
There is no entropy encoder back-end nor framing layer.
The latter is assumed to be handled by other parts of the system.
This design is assumed to favor simplicity and speed.

This document describes only the Block Format,
not how the compressor nor decompressor actually work.


Compressed block format
-----------------------
An LZ4 compressed block is composed of sequences.
A sequence is a suite of literals (not-compressed bytes),
followed by a match copy operation.

Each sequence starts with a `token`.
The `token` is a one byte value, separated into two 4-bits fields.
Therefore each field ranges from 0 to 15.


The first field uses the 4 high-bits of the token.
It provides the length of literals to follow.

If the field value is smaller than 15,
then it represents the total nb of literals present in the sequence,
including 0, in which case there is no literal.

The value 15 is a special case: more bytes are required to indicate the full length.
Each additional byte then represents a value from 0 to 255,
which is added to the previous value to produce a total length.
When the byte value is 255, another byte must be read and added, and so on.
There can be any number of bytes of value `255` following `token`.

Example 1 : A literal length of 48 will be represented as :

  - 15 : value for the 4-bits High field
  - 33 : (=48-15) remaining length to reach 48

Example 2 : A literal length of 280 will be represented as :

  - 15  : value for the 4-bits High field
  - 255 : following byte is maxed, since 280-15 >= 255
  - 10  : (=280 - 15 - 255) remaining length to reach 280

Example 3 : A literal length of 15 will be represented as :

  - 15 : value for the 4-bits High field
  - 0  : (=15-15) yes, the zero must be output

Following `token` and optional length bytes, are the literals themselves.
They are exactly as numerous as just decoded (length of literals).
Reminder: it's possible that there are zero literals.


Following the literals is the match copy operation.

It starts by the `offset` value.
This is a 2 bytes value, in little endian format
(the 1st byte is the "low" byte, the 2nd one is the "high" byte).

The `offset` represents the position of the match to be copied from the past.
For example, 1 means "current position - 1 byte".
The maximum `offset` value is 65535. 65536 and beyond cannot be coded.
Note that 0 is an invalid `offset` value.
The presence of a 0 `offset` value denotes an invalid (corrupted) block.

Then the `matchlength` can be extracted.
For this, we use the second `token` field, the low 4-bits.
Such a value, obviously, ranges from 0 to 15.
However here, 0 means that the copy operation is minimal.
The minimum length of a match, called `minmatch`, is 4.
As a consequence, a 0 value means 4 bytes.
Similarly to literal length, any value smaller than 15 represents a length,
to which 4 (`minmatch`) must be added, thus ranging from 4 to 18.
A value of 15 is special, meaning 19+ bytes,
to which one must read additional bytes, one at a time,
with each byte value ranging from 0 to 255.
They are added to total to provide the final match length.
A 255 value means there is another byte to read and add.
There is no limit to the number of optional `255` bytes that can be present,
and therefore no limit to representable match length.

Decoding the `matchlength` reaches the end of current sequence.
Next byte will be the start of another sequence, and therefore a new `token`.


End of block conditions
-------------------------
There are specific restrictions required to terminate an LZ4 block.

1. The last sequence contains only literals.
   The block ends right after the literals (no `offset` field).
2. The last 5 bytes of input are always literals.
   Therefore, the last sequence contains at least 5 bytes.
   - Special : if input is smaller than 5 bytes,
     there is only one sequence, it contains the whole input as literals.
     Even empty input can be represented, using a zero byte,
     interpreted as a final token without literal and without a match.
3. The last match must start at least 12 bytes before the end of block.
   The last match is part of the _penultimate_ sequence.
   It is followed by the last sequence, which contains _only_ literals.
   - Note that, as a consequence,
     blocks < 12 bytes cannot be compressed.
     And as an extension, _independent_ blocks < 13 bytes cannot be compressed,
     because they must start by at least one literal,
     that the match can then copy afterwards.

When a block does not respect these end conditions,
a conformant decoder is allowed to reject the block as incorrect.


Implementation notes
-----------------------
The LZ4 Block Format only defines the compressed format,
it does not tell how to create a decoder or an encoder,
which design is left free to the imagination of the implementer.

### Metadata

An LZ4-compressed Block requires additional metadata for proper decoding.
Typically, a decoder will require the compressed block's size,
and an upper bound of decompressed size.
The Block Format does not specify how to transmit such information.

### Safe decoding

If a decoder receives compressed data from any external source,
it is recommended to ensure that the decoder is resilient to corrupted input,
and made safe from buffer overflow manipulations.
Always ensure that read and write operations
remain within the limits of provided buffers.

Pay some attention to offset 0 scenario, which is invalid,
and therefore must not be blindly decoded.

Finally, pay attention to the "overlap match" scenario,
when `matchlength` is larger than `offset`.
In which case, since `match_pos + matchlength > current_pos`,
some of the later bytes to copy do not exist yet,
and will be generated during the early stage of match copy operation.
Such scenario must be handled with special care.
A common case is an offset of 1,
meaning the last byte is repeated `matchlength` times.
