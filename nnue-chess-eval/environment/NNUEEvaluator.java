import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/**
 * Evaluates chess positions using a quantized neural network.
 *
 * The network weights are loaded from a binary file containing
 * little-endian signed 16-bit integers in the following order:
 *   inputWeights[NUM_BUCKETS * INPUT_SIZE * HIDDEN_SIZE]
 *   inputBiases[HIDDEN_SIZE]
 *   outputWeights[2 * HIDDEN_SIZE]
 *   outputBias[1]
 *
 * Input weights are stored in row-major order: iterate over buckets,
 * then input features, then hidden neurons.
 */
public class NNUEEvaluator {

    private static final int INPUT_SIZE  = 768;
    private static final int HIDDEN_SIZE = 32;
    private static final int NUM_BUCKETS = 4;
    private static final int QA    = 255;
    private static final int QB    = 64;
    private static final int SCALE = 400;

    private static final int[] BUCKET_MAP = {
        0, 0, 1, 1, 1, 1, 0, 0,
        0, 0, 1, 1, 1, 1, 0, 0,
        2, 2, 2, 2, 2, 2, 2, 2,
        2, 2, 2, 2, 2, 2, 2, 2,
        2, 2, 2, 2, 2, 2, 2, 2,
        3, 3, 3, 3, 3, 3, 3, 3,
        3, 3, 3, 3, 3, 3, 3, 3,
        3, 3, 3, 3, 3, 3, 3, 3,
    };

    private static final int[] PHASE_WEIGHT = {0, 3, 3, 5, 10, 0};

    private final short[][][] inputWeights;
    private final short[] inputBiases;
    private final short[] outputWeights;
    private final short outputBias;

    public NNUEEvaluator(String networkPath) throws IOException {
        ByteBuffer buf = ByteBuffer.wrap(Files.readAllBytes(Path.of(networkPath)))
                                   .order(ByteOrder.LITTLE_ENDIAN);

        inputWeights = new short[NUM_BUCKETS][INPUT_SIZE][HIDDEN_SIZE];
        for (int b = 0; b < NUM_BUCKETS; b++)
            for (int i = 0; i < INPUT_SIZE; i++)
                for (int h = 0; h < HIDDEN_SIZE; h++)
                    inputWeights[b][i][h] = buf.getShort();

        inputBiases = new short[HIDDEN_SIZE];
        for (int h = 0; h < HIDDEN_SIZE; h++)
            inputBiases[h] = buf.getShort();

        outputWeights = new short[2 * HIDDEN_SIZE];
        for (int i = 0; i < 2 * HIDDEN_SIZE; i++)
            outputWeights[i] = buf.getShort();

        outputBias = buf.getShort();
    }

    /** Evaluate a FEN position. Returns centipawn score for the side to move. */
    public int evaluate(String fen) {
        Board board = new Board(fen);

        int[] whiteAcc = buildAccumulator(board, true);
        int[] blackAcc = buildAccumulator(board, false);

        int[] us, them;
        if (board.whiteToMove) {
            us   = whiteAcc;
            them = blackAcc;
        } else {
            us   = blackAcc;
            them = whiteAcc;
        }

        int eval = forwardPass(us, them);
        eval = eval * (22400 + materialPhase(board)) / 32768;
        eval = eval * (200 - board.halfmoveClock) / 200;
        return eval;
    }

    /** Returns sorted array of active feature indices for the given perspective. */
    public int[] getFeatures(String fen, boolean whitePerspective) {
        Board board = new Board(fen);
        return computeFeatures(board, whitePerspective);
    }

    private int[] computeFeatures(Board board, boolean whitePerspective) {
        int kingSquare = board.kingSquare(whitePerspective);
        boolean mirror = shouldMirror(kingSquare);

        int count = 0;
        int[] buffer = new int[32];

        for (int sq = 0; sq < 64; sq++) {
            int piece = board.squares[sq];
            if (piece == Board.EMPTY)
                continue;

            boolean pieceWhite = piece < 6;
            int pieceType = piece % 6;

            int relColor = (whitePerspective == pieceWhite) ? 0 : 1;

            int adjSq = sq;
            if (!whitePerspective) adjSq ^= 56;
            if (mirror)            adjSq ^= 7;

            buffer[count++] = relColor * 384 + pieceType * 64 + adjSq;
        }

        int[] features = Arrays.copyOf(buffer, count);
        Arrays.sort(features);
        return features;
    }

    private int[] buildAccumulator(Board board, boolean whitePerspective) {
        int kingSquare = board.kingSquare(whitePerspective);
        int bucket = inputBucket(kingSquare, whitePerspective);

        int[] acc = new int[HIDDEN_SIZE];
        for (int h = 0; h < HIDDEN_SIZE; h++)
            acc[h] = inputBiases[h];

        int[] features = computeFeatures(board, whitePerspective);
        for (int feat : features)
            for (int h = 0; h < HIDDEN_SIZE; h++)
                acc[h] += inputWeights[bucket][feat][h];

        return acc;
    }

    private int forwardPass(int[] us, int[] them) {
        int output = 0;
        for (int h = 0; h < HIDDEN_SIZE; h++) {
            output += activation(us[h])   * outputWeights[h];
            output += activation(them[h]) * outputWeights[HIDDEN_SIZE + h];
        }
        return (output / QA + outputBias) * SCALE / (QA * QB);
    }

    private int activation(int x) {
        int clamped = Math.max(0, Math.min(x, QA));
        return clamped * clamped;
    }

    private boolean shouldMirror(int kingSquare) {
        return (kingSquare & 7) > 3;
    }

    private int inputBucket(int kingSquare, boolean white) {
        int sq = white ? kingSquare : (kingSquare ^ 56);
        return BUCKET_MAP[sq];
    }

    private int materialPhase(Board board) {
        int phase = 0;
        for (int sq = 0; sq < 64; sq++) {
            int piece = board.squares[sq];
            if (piece != Board.EMPTY)
                phase += PHASE_WEIGHT[piece % 6];
        }
        return phase;
    }

    // ========== Inner class for board representation ==========

    static class Board {
        static final int EMPTY = -1;

        // squares[sq]: -1 = empty, 0..5 = white PNBRQK, 6..11 = black PNBRQK
        // Square mapping: a1=0, b1=1, ..., h1=7, a2=8, ..., h8=63
        final int[] squares = new int[64];
        boolean whiteToMove;
        int halfmoveClock;

        Board(String fen) {
            Arrays.fill(squares, EMPTY);
            String[] fields = fen.split("\\s+");

            int rank = 7, file = 0;
            for (int i = 0; i < fields[0].length(); i++) {
                char c = fields[0].charAt(i);
                if (c == '/') {
                    rank--;
                    file = 0;
                } else if (c >= '1' && c <= '8') {
                    file += c - '0';
                } else {
                    squares[rank * 8 + file] = encodePiece(c);
                    file++;
                }
            }

            whiteToMove = fields.length > 1 && fields[1].charAt(0) == 'w';
            halfmoveClock = fields.length > 4 ? Integer.parseInt(fields[4]) : 0;
        }

        int kingSquare(boolean white) {
            int target = white ? 5 : 11;
            for (int sq = 0; sq < 64; sq++)
                if (squares[sq] == target) return sq;
            throw new IllegalStateException("No king found");
        }

        private static int encodePiece(char c) {
            int base = Character.isUpperCase(c) ? 0 : 6;
            return base + switch (Character.toLowerCase(c)) {
                case 'p' -> 0;
                case 'n' -> 1;
                case 'b' -> 2;
                case 'r' -> 3;
                case 'q' -> 4;
                case 'k' -> 5;
                default -> throw new IllegalArgumentException("Bad piece: " + c);
            };
        }
    }

    // ========== CLI entry point ==========

    public static void main(String[] args) throws IOException {
        if (args.length < 2) {
            System.err.println("Usage: java NNUEEvaluator <network_path> <fen>");
            System.exit(1);
        }
        NNUEEvaluator evaluator = new NNUEEvaluator(args[0]);
        String fen = String.join(" ", Arrays.copyOfRange(args, 1, args.length));

        int score = evaluator.evaluate(fen);
        System.out.println("eval: " + score);

        int[] whiteFeatures = evaluator.getFeatures(fen, true);
        int[] blackFeatures = evaluator.getFeatures(fen, false);
        System.out.println("white features: " + Arrays.toString(whiteFeatures));
        System.out.println("black features: " + Arrays.toString(blackFeatures));
    }
}
