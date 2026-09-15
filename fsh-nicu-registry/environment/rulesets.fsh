RuleSet: ExtensionContext(path)
* context[+].type = #element
* context[=].expression = "{path}"

RuleSet: DocumentExtension(path, short, definition)
* extension[{path}] ^short = {short}
* extension[{path}] ^definition = {definition}

RuleSet: CommonNICUObservationRules
* status MS
* code MS
* subject MS
* effective[x] MS
