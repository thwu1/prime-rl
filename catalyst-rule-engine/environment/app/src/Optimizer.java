
/**
 * The main query plan optimizer.
 * Loads its configuration from a properties file and applies rules via the RuleExecutor.
 */
public class Optimizer {
    private final RuleExecutor executor;

    public Optimizer() {
        this.executor = ConfigLoader.loadFromConfig("config/optimizer.properties");
    }

    public Plan optimize(Plan plan) {
        return executor.execute(plan);
    }
}
