import { Protocol, MessageType, Flags, LogLevel } from "./protocol";
import { Connection, Transport } from "./transport";
import { Middleware } from "./middleware";
import { ServiceRegistry, Registry } from "./registry";

const results: Record<string, unknown> = {};

// 1. Numeric enum reverse mapping
results["protocol_name_1"] = Protocol.toName(Protocol.HTTP);
results["protocol_name_2"] = Protocol.toName(Protocol.HTTPS);
results["protocol_name_4"] = Protocol.toName(Protocol.WSS);

// 2. Namespace-enum merged functions
results["is_secure_http"] = Protocol.isSecure(Protocol.HTTP);
results["is_secure_https"] = Protocol.isSecure(Protocol.HTTPS);
results["is_secure_wss"] = Protocol.isSecure(Protocol.WSS);

// 3. allNames via Object.keys filtering
results["protocol_names"] = Protocol.allNames();

// 4. String enum values
results["msg_type_request"] = MessageType.Request;
results["msg_type_response"] = MessageType.Response;

// 5. Const enum flags
const flags = Flags.Compressed | Flags.Encrypted;
results["flags_value"] = flags;
results["has_compressed"] = (flags & Flags.Compressed) !== 0;
results["has_signed"] = (flags & Flags.Signed) !== 0;
results["all_flags"] = Flags.All;

// 6. Heterogeneous enum + reverse mapping
results["log_debug"] = LogLevel.Debug;
results["log_error"] = LogLevel.Error;
results["log_debug_name"] = LogLevel.getNumericName(0);
results["log_info_name"] = LogLevel.getNumericName(1);
results["log_is_numeric_debug"] = LogLevel.isNumeric(LogLevel.Debug);
results["log_is_numeric_error"] = LogLevel.isNumeric(LogLevel.Error);

// 7. Parameter properties (Connection class)
const conn = new Connection(
    "localhost",
    8080,
    Protocol.HTTP,
    Flags.Compressed | Flags.Encrypted
);
results["conn_host"] = conn.host;
results["conn_port"] = conn.port;
results["conn_protocol"] = conn.getProtocol();
results["conn_compressed"] = conn.isCompressed();
results["conn_encrypted"] = conn.isEncrypted();
results["conn_describe"] = conn.describe();

// 8. Namespace with class (Transport.Pool)
const pool = Transport.createDefault();
results["pool_max"] = pool.getMaxSize();
results["pool_size_0"] = pool.size();
pool.add(conn);
results["pool_size_1"] = pool.size();

// 9. Middleware (parameter properties + TrackedComponent + namespace-class merge)
const mw1 = Middleware.create("auth", 10, Protocol.HTTPS);
const mw2 = Middleware.create("logging", 5, Protocol.HTTP);
const mw3 = Middleware.create("compress", 15, Protocol.WS);

results["mw_name"] = mw1.name;
results["mw_priority"] = mw1.priority;
results["mw_protocol"] = mw1.getProtocol();
results["mw_mutations"] = mw1.getMutations();
results["mw_mutation_count"] = mw1.getMutationCount();
results["mw_describe"] = mw1.describe();

const sorted = Middleware.sortByPriority([mw1, mw2, mw3]);
results["mw_sorted_names"] = sorted.map(m => m.name);
results["mw_sorted_priorities"] = sorted.map(m => m.priority);

results["mw2_mutation_count"] = mw2.getMutationCount();

// 10. Post-construction mutation tracking
const mwMutTest = new Middleware("test", 1, Protocol.HTTP);
results["mw_initial_mutations"] = mwMutTest.getMutationCount();
mwMutTest.name = "test-v2";
mwMutTest.priority = 99;
results["mw_after_update_mutations"] = mwMutTest.getMutationCount();
results["mw_after_update_name"] = mwMutTest.name;
results["mw_after_update_priority"] = mwMutTest.priority;

// 11. Registry (namespace + import alias + parameter property)
const registry = new ServiceRegistry("main", 3);
const entry = Registry.createEntry("api", Protocol.HTTPS);
entry.messageTypes.push(MessageType.Request, MessageType.Response);
registry.register(entry);
results["registry_name"] = registry.getRegistryName();
results["registry_count"] = registry.getServiceCount();
results["registry_entry"] = registry.getEntry("api");
results["registry_pool_max"] = registry.getPool().getMaxSize();

console.log(JSON.stringify(results, null, 2));
