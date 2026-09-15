package main

// Merge merges two decoded protobuf messages according to protobuf merge semantics.
// Rules:
//   - Scalar fields: last one wins (msg2 overrides msg1)
//   - Submessage fields: recursive merge
//   - Repeated fields: concatenation
func Merge(schema *Schema, msg1, msg2 map[string]interface{}) map[string]interface{} {
	result := make(map[string]interface{})

	// Copy all fields from msg1.
	for k, v := range msg1 {
		result[k] = v
	}

	// Merge fields from msg2.
	for k, v := range msg2 {
		field := schema.FieldByName(k)
		if field == nil {
			result[k] = v
			continue
		}

		if field.Repeated {
			existing, ok := result[k]
			if ok {
				existingArr, _ := existing.([]interface{})
				newArr, _ := v.([]interface{})
				result[k] = append(existingArr, newArr...)
			} else {
				result[k] = v
			}
		} else if field.Type == TypeMessage {
			// Submessage: should recursively merge but currently replaces.
			result[k] = v
		} else {
			result[k] = v
		}
	}

	return result
}
