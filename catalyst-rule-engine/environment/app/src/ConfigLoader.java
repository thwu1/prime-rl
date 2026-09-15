import java.io.*;
import java.util.*;


/**
 * Loads optimizer configuration from a properties file.
 * The config specifies rule batches, their execution strategy, and which rules to include.
 */
public class ConfigLoader {

    /**
     * Load an optimizer configuration and construct a RuleExecutor.
     * @param configPath path to the .properties file
     */
    public static RuleExecutor loadFromConfig(String configPath) {
        Properties props = new Properties();
        try (FileInputStream fis = new FileInputStream(configPath)) {
            props.load(fis);
        } catch (IOException e) {
            throw new RuntimeException("Cannot load optimizer config: " + configPath, e);
        }

        String batchName = props.getProperty("batch.name", "Default");
        String strategyStr = props.getProperty("batch.strategy", "once").trim();
        int maxIter = Integer.parseInt(props.getProperty("batch.maxIterations", "10").trim());
        String rulesStr = props.getProperty("batch.rules", "");

        RuleExecutor.Strategy strategy;
        if ("fixed_point".equals(strategyStr)) {
            strategy = RuleExecutor.Strategy.FIXED_POINT;
        } else {
            strategy = RuleExecutor.Strategy.ONCE;
        }

        List<Rule> rules = new ArrayList<>();
        for (String ruleName : rulesStr.split(",")) {
            ruleName = ruleName.trim();
            if (!ruleName.isEmpty()) {
                rules.add(instantiateRule(ruleName));
            }
        }

        RuleExecutor.Batch batch = new RuleExecutor.Batch(
            batchName, strategy, maxIter, rules.toArray(new Rule[0]));
        return new RuleExecutor(List.of(batch));
    }

    private static Rule instantiateRule(String className) {
        try {
            Class<?> clz = Class.forName(className);
            return (Rule) clz.getDeclaredConstructor().newInstance();
        } catch (Exception e) {
            throw new RuntimeException("Cannot instantiate rule: " + className, e);
        }
    }
}
