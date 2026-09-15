package cdm;

import com.google.gson.*;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

/**
 * CDM BusinessEvent Qualifier - Reference Implementation.
 *
 * Classifies ISDA CDM BusinessEvent JSON documents into lifecycle event types
 * by analyzing structural characteristics according to CDM qualification rules.
 */
public class EventQualifier {

    public static void main(String[] args) throws Exception {
        if (args.length != 1) {
            System.err.println("Usage: java cdm.EventQualifier <event.json>");
            System.exit(1);
        }
        String json = Files.readString(Path.of(args[0]));
        JsonObject event = JsonParser.parseString(json).getAsJsonObject();
        System.out.println(qualify(event));
    }

    // ============================================================
    // Main qualification dispatch
    // ============================================================

    static String qualify(JsonObject event) {
        String intent = optStr(event, "intent");
        JsonArray instructions = getArr(event, "instruction");
        JsonArray afterStates = getArr(event, "after");

        List<JsonObject> closedStates = filterClosedTradeStates(afterStates);
        List<JsonObject> openStates = filterOpenTradeStates(afterStates);

        // Intent-based qualifiers first (they have explicit intent fields)
        if (isNovation(event, intent, instructions, closedStates, openStates)) return "Novation";
        if (isPartialNovation(event, intent, instructions, closedStates, openStates)) return "PartialNovation";
        if (isAllocation(intent, instructions, closedStates, openStates)) return "Allocation";
        if (isClearedTrade(event, intent, instructions, closedStates, openStates)) return "ClearedTrade";

        // Multi-instruction qualifier
        if (isCompression(instructions)) return "Compression";

        // Single-instruction, primitive-type qualifiers
        if (isContractFormation(event, intent, instructions)) return "ContractFormation";
        if (isExecution(intent, instructions)) return "Execution";

        // Quantity-change qualifiers (order matters: termination before partial, partial before increase)
        if (isTermination(intent, instructions, afterStates)) return "Termination";
        if (isPartialTermination(intent, instructions, afterStates)) return "PartialTermination";
        if (isIncrease(intent, instructions, afterStates)) return "Increase";

        return "Unknown";
    }

    // ============================================================
    // Qualification predicates
    // ============================================================

    static boolean isNovation(JsonObject event, String intent, JsonArray instructions,
                              List<JsonObject> closedStates, List<JsonObject> openStates) {
        if (!"Novation".equals(intent)) return false;
        if (closedStates.size() != 1 || openStates.size() != 1) return false;
        if (!hasSplitAcrossInstructions(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        Set<String> beforeParties = getPartyRefs(beforeTrade);
        Set<String> closedParties = getPartyRefs(getTrade(closedStates.get(0)));
        Set<String> openParties = getPartyRefs(getTrade(openStates.get(0)));

        Set<String> beforeIds = getTradeIds(beforeTrade);
        Set<String> openIds = getTradeIds(getTrade(openStates.get(0)));

        return beforeParties.equals(closedParties)
            && !beforeParties.equals(openParties)
            && !beforeIds.equals(openIds);
    }

    static boolean isPartialNovation(JsonObject event, String intent, JsonArray instructions,
                                     List<JsonObject> closedStates, List<JsonObject> openStates) {
        if (!"Novation".equals(intent)) return false;
        if (closedStates.size() != 0 || openStates.size() != 2) return false;
        if (!hasSplitAcrossInstructions(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        Set<String> beforeParties = getPartyRefs(beforeTrade);
        Set<String> beforeIds = getTradeIds(beforeTrade);
        List<Double> beforeQtys = getQuantities(beforeTrade);

        for (JsonObject openState : openStates) {
            JsonObject trade = getTrade(openState);
            Set<String> parties = getPartyRefs(trade);
            Set<String> ids = getTradeIds(trade);

            boolean isDifferentParty = !parties.equals(beforeParties) && !ids.equals(beforeIds);
            boolean isSameWithDecrease = parties.equals(beforeParties) && ids.equals(beforeIds)
                && quantityDecreased(beforeQtys, getQuantities(trade));

            if (!isDifferentParty && !isSameWithDecrease) return false;
        }
        return true;
    }

    static boolean isAllocation(String intent, JsonArray instructions,
                                List<JsonObject> closedStates, List<JsonObject> openStates) {
        if (!"Allocation".equals(intent)) return false;
        if (closedStates.size() != 1 || openStates.size() < 1) return false;
        if (!hasSplitAcrossInstructions(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        Set<String> beforeParties = getPartyRefs(beforeTrade);
        Set<String> closedParties = getPartyRefs(getTrade(closedStates.get(0)));

        if (!beforeParties.equals(closedParties)) return false;

        for (JsonObject openState : openStates) {
            Set<String> openParties = getPartyRefs(getTrade(openState));
            if (beforeParties.equals(openParties)) return false;
        }
        return true;
    }

    static boolean isClearedTrade(JsonObject event, String intent, JsonArray instructions,
                                  List<JsonObject> closedStates, List<JsonObject> openStates) {
        if (!"Clearing".equals(intent)) return false;
        if (closedStates.size() != 1 || openStates.size() != 2) return false;
        if (!hasSplitAcrossInstructions(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        Set<String> beforeParties = getPartyRefs(beforeTrade);
        Set<String> beforeIds = getTradeIds(beforeTrade);
        Set<String> closedParties = getPartyRefs(getTrade(closedStates.get(0)));

        if (!beforeParties.equals(closedParties)) return false;

        for (JsonObject openState : openStates) {
            JsonObject trade = getTrade(openState);
            Set<String> openParties = getPartyRefs(trade);
            Set<String> openIds = getTradeIds(trade);

            if (beforeParties.equals(openParties)) return false;
            if (beforeIds.equals(openIds)) return false;
            if (!hasPartyRole(trade, "ClearingOrganization")) return false;
        }
        return true;
    }

    static boolean isCompression(JsonArray instructions) {
        if (instructions == null || instructions.size() < 2) return false;
        int execCount = 0;
        int qcCount = 0;
        for (JsonElement instrEl : instructions) {
            JsonObject pi = getObj(instrEl.getAsJsonObject(), "primitiveInstruction");
            if (pi == null) continue;
            if (pi.has("execution") && !pi.get("execution").isJsonNull()) execCount++;
            if (pi.has("quantityChange") && !pi.get("quantityChange").isJsonNull()) qcCount++;
        }
        return execCount == 1 && qcCount > 1;
    }

    static boolean isContractFormation(JsonObject event, String intent, JsonArray instructions) {
        if (instructions == null || instructions.size() != 1) return false;
        JsonObject pi = getObj(instructions.get(0).getAsJsonObject(), "primitiveInstruction");

        if (pi == null || pi.isJsonNull()) {
            return "ContractFormation".equals(intent);
        }

        Set<String> present = getPresentPrimitives(pi);

        return present.equals(Set.of("contractFormation"))
            || present.equals(Set.of("contractFormation", "transfer"))
            || present.equals(Set.of("execution", "contractFormation"))
            || present.equals(Set.of("execution", "contractFormation", "transfer"));
    }

    static boolean isExecution(String intent, JsonArray instructions) {
        if (intent != null) return false;
        if (instructions == null || instructions.size() != 1) return false;
        JsonObject pi = getObj(instructions.get(0).getAsJsonObject(), "primitiveInstruction");
        if (pi == null) return false;

        Set<String> present = getPresentPrimitives(pi);
        return present.equals(Set.of("execution"))
            || present.equals(Set.of("execution", "transfer"));
    }

    static boolean isTermination(String intent, JsonArray instructions, JsonArray afterStates) {
        if (intent != null) return false;
        if (!isSingleInstructionWithOnlyQuantityChange(instructions)) return false;

        // All quantities in after must be zero
        if (!allQuantitiesZero(afterStates)) return false;

        // All after states must have closedState = Terminated
        for (JsonElement el : afterStates) {
            JsonObject state = getObj(el.getAsJsonObject(), "state");
            if (state == null) return false;
            JsonObject closedState = getObj(state, "closedState");
            if (closedState == null) return false;
            String s = optStr(closedState, "state");
            if (!"Terminated".equals(s)) return false;
        }
        return true;
    }

    static boolean isPartialTermination(String intent, JsonArray instructions, JsonArray afterStates) {
        if (intent != null) return false;
        if (!isSingleInstructionWithOnlyQuantityChange(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        List<Double> beforeQtys = getQuantities(beforeTrade);

        // Get after quantities from the first (only) after state
        boolean anyDecreased = false;
        for (JsonElement el : afterStates) {
            JsonObject trade = getTrade(el.getAsJsonObject());
            if (trade == null) continue;
            List<Double> afterQtys = getQuantities(trade);
            if (quantityDecreased(beforeQtys, afterQtys)) anyDecreased = true;

            // closedState must be absent
            JsonObject state = getObj(el.getAsJsonObject(), "state");
            if (state != null) {
                JsonObject closedState = getObj(state, "closedState");
                if (closedState != null) return false;
            }
        }

        // Must have decreased but not to zero
        return anyDecreased && !allQuantitiesZero(afterStates);
    }

    static boolean isIncrease(String intent, JsonArray instructions, JsonArray afterStates) {
        if (intent != null) return false;
        if (!isSingleInstructionWithOnlyQuantityChange(instructions)) return false;

        JsonObject beforeTrade = getBeforeTrade(instructions);
        if (beforeTrade == null) return false;

        List<Double> beforeQtys = getQuantities(beforeTrade);

        for (JsonElement el : afterStates) {
            JsonObject trade = getTrade(el.getAsJsonObject());
            if (trade == null) continue;
            List<Double> afterQtys = getQuantities(trade);
            if (quantityIncreased(beforeQtys, afterQtys)) return true;
        }
        return false;
    }

    // ============================================================
    // Helper functions
    // ============================================================

    static List<JsonObject> filterClosedTradeStates(JsonArray afterStates) {
        List<JsonObject> result = new ArrayList<>();
        if (afterStates == null) return result;
        for (JsonElement el : afterStates) {
            JsonObject ts = el.getAsJsonObject();
            JsonObject state = getObj(ts, "state");
            if (state != null) {
                JsonObject closedState = getObj(state, "closedState");
                if (closedState != null) {
                    result.add(ts);
                }
            }
        }
        return result;
    }

    static List<JsonObject> filterOpenTradeStates(JsonArray afterStates) {
        List<JsonObject> result = new ArrayList<>();
        if (afterStates == null) return result;
        for (JsonElement el : afterStates) {
            JsonObject ts = el.getAsJsonObject();
            JsonObject state = getObj(ts, "state");
            boolean isClosed = false;
            if (state != null) {
                JsonObject closedState = getObj(state, "closedState");
                if (closedState != null) isClosed = true;
            }
            if (!isClosed) result.add(ts);
        }
        return result;
    }

    static Set<String> getPartyRefs(JsonObject trade) {
        Set<String> refs = new TreeSet<>();
        if (trade == null) return refs;
        JsonArray counterparties = getArr(trade, "counterparty");
        if (counterparties == null) return refs;
        for (JsonElement cp : counterparties) {
            JsonObject partyRef = getObj(cp.getAsJsonObject(), "partyReference");
            if (partyRef == null) continue;
            String ext = optStr(partyRef, "@ref:external");
            if (ext == null) ext = optStr(partyRef, "@key:external");
            if (ext != null) refs.add(ext);
        }
        return refs;
    }

    static Set<String> getTradeIds(JsonObject trade) {
        Set<String> ids = new TreeSet<>();
        if (trade == null) return ids;
        JsonArray tids = getArr(trade, "tradeIdentifier");
        if (tids == null) return ids;
        for (JsonElement tidEl : tids) {
            JsonArray aids = getArr(tidEl.getAsJsonObject(), "assignedIdentifier");
            if (aids == null) continue;
            for (JsonElement aiEl : aids) {
                JsonObject ident = getObj(aiEl.getAsJsonObject(), "identifier");
                if (ident != null) {
                    String data = optStr(ident, "@data");
                    if (data != null) ids.add(data);
                }
            }
        }
        return ids;
    }

    static List<Double> getQuantities(JsonObject trade) {
        List<Double> quantities = new ArrayList<>();
        if (trade == null) return quantities;
        JsonArray tradeLots = getArr(trade, "tradeLot");
        if (tradeLots == null) return quantities;
        for (JsonElement lotEl : tradeLots) {
            JsonArray pqs = getArr(lotEl.getAsJsonObject(), "priceQuantity");
            if (pqs == null) continue;
            for (JsonElement pqEl : pqs) {
                JsonArray qs = getArr(pqEl.getAsJsonObject(), "quantity");
                if (qs == null) continue;
                for (JsonElement qEl : qs) {
                    JsonElement valEl = qEl.getAsJsonObject().get("value");
                    if (valEl != null && !valEl.isJsonNull()) {
                        quantities.add(valEl.getAsDouble());
                    }
                }
            }
        }
        return quantities;
    }

    static boolean hasPartyRole(JsonObject trade, String role) {
        if (trade == null) return false;
        JsonArray roles = getArr(trade, "partyRole");
        if (roles == null) return false;
        for (JsonElement roleEl : roles) {
            String r = optStr(roleEl.getAsJsonObject(), "role");
            if (role.equals(r)) return true;
        }
        return false;
    }

    static Set<String> getPresentPrimitives(JsonObject pi) {
        Set<String> present = new TreeSet<>();
        String[] primitiveNames = {
            "contractFormation", "execution", "exercise", "partyChange",
            "quantityChange", "reset", "split", "termsChange", "transfer",
            "indexTransition", "stockSplit", "observation", "valuation"
        };
        for (String name : primitiveNames) {
            if (pi.has(name) && !pi.get(name).isJsonNull()) {
                present.add(name);
            }
        }
        return present;
    }

    static boolean hasSplitAcrossInstructions(JsonArray instructions) {
        if (instructions == null) return false;
        for (JsonElement instrEl : instructions) {
            JsonObject pi = getObj(instrEl.getAsJsonObject(), "primitiveInstruction");
            if (pi != null && pi.has("split") && !pi.get("split").isJsonNull()) return true;
        }
        return false;
    }

    static boolean isSingleInstructionWithOnlyQuantityChange(JsonArray instructions) {
        if (instructions == null || instructions.size() != 1) return false;
        JsonObject pi = getObj(instructions.get(0).getAsJsonObject(), "primitiveInstruction");
        if (pi == null) return false;
        Set<String> present = getPresentPrimitives(pi);
        return present.equals(Set.of("quantityChange"))
            || present.equals(Set.of("quantityChange", "transfer"));
    }

    static JsonObject getBeforeTrade(JsonArray instructions) {
        if (instructions == null) return null;
        for (JsonElement instrEl : instructions) {
            JsonObject before = getObj(instrEl.getAsJsonObject(), "before");
            if (before != null && !before.isJsonNull()) {
                return getTrade(before);
            }
        }
        return null;
    }

    static JsonObject getTrade(JsonObject tradeState) {
        if (tradeState == null) return null;
        return getObj(tradeState, "trade");
    }

    static boolean quantityDecreased(List<Double> before, List<Double> after) {
        if (before.isEmpty() || after.isEmpty()) return false;
        double beforeSum = before.stream().mapToDouble(Double::doubleValue).sum();
        double afterSum = after.stream().mapToDouble(Double::doubleValue).sum();
        return afterSum < beforeSum;
    }

    static boolean quantityIncreased(List<Double> before, List<Double> after) {
        if (before.isEmpty() || after.isEmpty()) return false;
        double beforeSum = before.stream().mapToDouble(Double::doubleValue).sum();
        double afterSum = after.stream().mapToDouble(Double::doubleValue).sum();
        return afterSum > beforeSum;
    }

    static boolean allQuantitiesZero(JsonArray afterStates) {
        if (afterStates == null) return false;
        for (JsonElement el : afterStates) {
            JsonObject trade = getTrade(el.getAsJsonObject());
            if (trade == null) continue;
            List<Double> qtys = getQuantities(trade);
            for (double q : qtys) {
                if (Math.abs(q) > 1e-10) return false;
            }
        }
        return true;
    }

    // ============================================================
    // JSON navigation helpers
    // ============================================================

    static String optStr(JsonObject obj, String key) {
        if (obj == null || !obj.has(key)) return null;
        JsonElement el = obj.get(key);
        if (el.isJsonNull()) return null;
        if (el.isJsonPrimitive()) return el.getAsString();
        return null;
    }

    static JsonObject getObj(JsonObject obj, String key) {
        if (obj == null || !obj.has(key)) return null;
        JsonElement el = obj.get(key);
        if (el.isJsonNull()) return null;
        if (el.isJsonObject()) return el.getAsJsonObject();
        return null;
    }

    static JsonArray getArr(JsonObject obj, String key) {
        if (obj == null || !obj.has(key)) return null;
        JsonElement el = obj.get(key);
        if (el.isJsonNull()) return null;
        if (el.isJsonArray()) return el.getAsJsonArray();
        return null;
    }
}
