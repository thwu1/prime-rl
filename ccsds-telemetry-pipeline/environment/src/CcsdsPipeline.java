import java.io.*;
import java.util.*;

/**
 * CCSDS TM Telemetry Processing Pipeline.
 *
 * Reads randomized TM transfer frames from a binary file,
 * derandomizes them, verifies CRC, parses headers, extracts
 * embedded CCSDS Space Packets, and writes structured JSON output.
 */
public class CcsdsPipeline {
    private static final int FRAME_LENGTH = 256;
    private static final boolean HAS_CRC = true;

    public static void main(String[] args) throws Exception {
        String inputFile = args.length > 0 ? args[0] : "/app/telemetry.bin";
        String outputFile = args.length > 1 ? args[1] : "/app/output.json";

        byte[] allData = readFile(inputFile);
        int numFrames = allData.length / FRAME_LENGTH;

        TmFrameDecoder decoder = new TmFrameDecoder(FRAME_LENGTH, HAS_CRC);
        PacketExtractor extractor = new PacketExtractor();

        StringBuilder framesJson = new StringBuilder();
        StringBuilder packetsJson = new StringBuilder();
        int packetIndex = 0;

        for (int i = 0; i < numFrames; i++) {
            int offset = i * FRAME_LENGTH;

            // Step 1: Derandomize the frame
            Randomizer.derandomize(allData, offset, FRAME_LENGTH);

            // Step 2: Decode frame header and verify CRC
            TmFrame frame = decoder.decode(allData, offset);

            // Build frame JSON entry
            if (i > 0) framesJson.append(",\n");
            framesJson.append(String.format(
                "    {\"index\": %d, \"spacecraftId\": %d, \"vcid\": %d, " +
                "\"mcFrameCount\": %d, \"vcFrameCount\": %d, " +
                "\"firstHeaderPointer\": %d, \"ocf\": \"0x%08X\", \"crcValid\": %s}",
                i, frame.spacecraftId, frame.vcid,
                frame.mcFrameCount, frame.vcFrameCount,
                frame.firstHeaderPointer, frame.ocf, frame.crcValid));

            // Step 3: Extract space packets from frame data field
            List<SpacePacket> packets = extractor.extractPackets(frame);
            for (SpacePacket pkt : packets) {
                if (packetIndex > 0) packetsJson.append(",\n");
                packetsJson.append(String.format(
                    "    {\"index\": %d, \"apid\": %d, \"sequenceFlags\": %d, " +
                    "\"sequenceCount\": %d, \"dataLength\": %d, \"userDataHex\": \"%s\"}",
                    packetIndex, pkt.apid, pkt.sequenceFlags,
                    pkt.sequenceCount, pkt.dataLength, bytesToHex(pkt.userData)));
                packetIndex++;
            }
        }

        String json = "{\n  \"frames\": [\n" + framesJson + "\n  ],\n" +
                      "  \"packets\": [\n" + packetsJson + "\n  ]\n}";

        try (FileWriter fw = new FileWriter(outputFile)) {
            fw.write(json);
        }

        System.out.println("Processed " + numFrames + " frames, extracted " + packetIndex + " packets");
    }

    private static byte[] readFile(String path) throws IOException {
        File file = new File(path);
        byte[] data = new byte[(int) file.length()];
        try (FileInputStream fis = new FileInputStream(file)) {
            int bytesRead = 0;
            while (bytesRead < data.length) {
                int n = fis.read(data, bytesRead, data.length - bytesRead);
                if (n == -1) break;
                bytesRead += n;
            }
        }
        return data;
    }

    private static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder();
        for (byte b : bytes) {
            sb.append(String.format("%02x", b & 0xFF));
        }
        return sb.toString();
    }
}
