---
title: Upgrade to OpenAI Python SDK v1.X
tags: [python, openai, migration]
---

Convert OpenAI from openai version to the v1 version.

This is a reference example of a complex GritQL migration pattern. Study the
pattern composition, sub-pattern definitions, sequential logic, bubble scoping,
import management, and exception remapping techniques used here.

```grit
engine marzano(0.1)
language python

pattern rename_resource() {
	or {
		`Audio` => `audio`,
		`ChatCompletion` => `chat.completions`,
		`Completion` => `completions`,
		`Edit` => `edits`,
		`Embedding` => `embeddings`,
		`File` => `files`,
		`FineTune` => `fine_tunes`,
		`FineTuningJob` => `fine_tuning`,
		`Image` => `images`,
		`Model` => `models`,
		`Moderation` => `moderations`
	}
}

pattern rename_resource_cls() {
	or {
		r"Audio" => `resources.Audio`,
		r"ChatCompletion" => `resources.chat.Completions`,
		r"Completion" => `resources.Completions`,
		r"Edit" => `resources.Edits`,
		r"Embedding" => `resources.Embeddings`,
		r"File" => `resources.Files`,
		r"FineTune" => `resources.FineTunes`,
		r"FineTuningJob" => `resources.FineTuning`,
		r"Image" => `resources.Images`,
		r"Model" => `resources.Models`,
		r"Moderation" => `resources.Moderations`
	}
}

pattern deprecated_resource() {
	or {
		`Customer`,
		`Deployment`,
		`Engine`,
		`ErrorObject`
	}
}

pattern deprecated_resource_cls() {
	or {
		r"Customer",
		r"Deployment",
		r"Engine",
		r"ErrorObject"
	}
}

pattern rename_func($has_sync, $has_async, $res, $stmt, $params, $client) {
	$func where {
		if ($func <: r"a([a-zA-Z0-9]+)"($func_rest)) {
			$has_async = `true`,
			$func => $func_rest,
			if ($client <: undefined) {
				$stmt => `aclient.$res.$func($params)`
			} else { $stmt => `$client.$res.$func($params)` }
		} else {
			$has_sync = `true`,
			if ($client <: undefined) { $stmt => `client.$res.$func($params)` } else {
				$stmt => `$client.$res.$func($params)`
			}
		},
		if ($res <: `Image`) { $func => `generate` }
	}
}

pattern change_import($has_sync, $has_async, $need_openai_import, $azure, $client_params) {
	$stmt where {
		$imports_and_defs = [],
		if ($need_openai_import <: `true`) { $imports_and_defs += `import openai` },
		if ($azure <: true) {
			$client = `AzureOpenAI`,
			$aclient = `AsyncAzureOpenAI`
		} else { $client = `OpenAI`, $aclient = `AsyncOpenAI` },
		$formatted_params = join(list=$client_params, separator=`,\n`),
		if (and { $has_sync <: `true`, $has_async <: `true` }) {
			$imports_and_defs += `from openai import $client, $aclient`,
			$imports_and_defs += ``,
			$imports_and_defs += `client = $client($formatted_params)`,
			$imports_and_defs += `aclient = $aclient($formatted_params)`
		} else if ($has_sync <: `true`) {
			$imports_and_defs += `from openai import $client`,
			$imports_and_defs += ``,
			$imports_and_defs += `client = $client($formatted_params)`
		} else if ($has_async <: `true`) {
			$imports_and_defs += `from openai import $aclient`,
			$imports_and_defs += ``,
			$imports_and_defs += `aclient = $aclient($formatted_params)`
		},
		$formatted = join(list=$imports_and_defs, separator=`\n`),
		$stmt => `$formatted`
	}
}

pattern rewrite_whole_fn_call($import, $has_sync, $has_async, $res, $func, $params, $stmt, $body, $client, $azure) {
	or {
		rename_resource() where {
			$import = `true`,
			$func <: rename_func($has_sync, $has_async, $res, $stmt, $params, $client),
			if ($azure <: true) {
				$params <: maybe contains bubble `engine` => `model`
			}
		},
		deprecated_resource() as $dep_res where {
			$stmt_whole = $stmt,
			if ($body <: contains `$_ = $stmt` as $line) { $stmt_whole = $line },
			$stmt_whole => todo(message=`The resource '$dep_res' has been deprecated`, target=$stmt_whole)
		}
	}
}

pattern fix_object_accessing($var) {
	or {
		`$x['$y']` as $sub => `$x.$y` where { $sub <: contains $var },
		`$x.get("$y")` => `$x.$y` where { $x <: contains $var }
	}
}

pattern fix_downstream_openai_usage() {
	$var where {
		$program <: maybe contains fix_object_accessing($var),
		$program <: maybe contains `for $chunk in $var: $body` where {
			$body <: maybe contains fix_object_accessing($chunk)
		}
	}
}

pattern openai_main($client, $azure) {
	$body where {
		if ($client <: undefined) {
			$need_openai_import = `false`,
			$create_client = true
		} else { $need_openai_import = `true`, $create_client = false },
		if ($azure <: undefined) { $azure = false },
		$has_openai_import = `false`,
		$has_partial_import = `false`,
		$has_sync = `false`,
		$has_async = `false`,
		$client_params = [],
		$body <: any {
			if ($client <: undefined) {
				contains bubble($need_openai_import, $azure, $client_params) `openai.$field = $val` as $setter where {
					$field <: or {
						`api_type` where {
							$res = .,
							if ($val <: or {
								`"azure"`,
								`"azure_ad"`
							}) { $azure = true }
						},
						`api_base` where {
							$azure <: true,
							$client_params += `azure_endpoint=$val`,
							$res = .
						},
						`api_key` where { $res = ., $client_params += `api_key=$val` },
						`api_version` where {
							$res = .,
							$azure = true,
							$client_params += `api_version=$val`
						},
						$_ where {
							if ($field <: `api_base`) { $new_name = `base_url` } else {
								$new_name = $field
							},
							$res = todo(message=`The 'openai.$field' option isn't read in the client API. You will need to pass it when you instantiate the client, e.g. 'OpenAI($new_name=$val)'`, target=$setter),
							$need_openai_import = `true`
						}
					}
				} => $res
			},
			contains bubble($need_openai_import) `openai.error.$exp` => `openai.$exp` where {
				$need_openai_import = `true`
			},
			contains `import openai` as $import_stmt where {
				$body <: contains bubble($has_sync, $has_async, $has_openai_import, $body, $client, $azure) `openai.$res.$func($params)` as $stmt where {
					$res <: rewrite_whole_fn_call(import=$has_openai_import, $has_sync, $has_async, $res, $func, $params, $stmt, $body, $client, $azure),
					$stmt <: maybe within bubble($stmt) `$var = $stmt` where {
						$var <: fix_downstream_openai_usage()
					}
				}
			},
			contains `from openai import $resources` as $partial_import_stmt where {
				$has_partial_import = `true`,
				$body <: contains bubble($has_sync, $has_async, $resources, $client, $azure) `$res.$func($params)` as $stmt where {
					$resources <: contains $res,
					$res <: rewrite_whole_fn_call($import, $has_sync, $has_async, $res, $func, $params, $stmt, $body, $client, $azure)
				}
			}
		},
		if ($create_client <: true) {
			if ($has_openai_import <: `true`) {
				$import_stmt <: change_import($has_sync, $has_async, $need_openai_import, $azure, $client_params),
				if ($has_partial_import <: `true`) { $partial_import_stmt => . }
			} else if ($has_partial_import <: `true`) {
				$partial_import_stmt <: change_import($has_sync, $has_async, $need_openai_import, $azure, $client_params)
			}
		}
	}
}

file($body) where {
	$body <: openai_main()
}
```

## Change openai import to Sync

```python
import openai

completion = openai.Completion.create(model="davinci-002", prompt="Hello world")
chat_completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": "Hello world"}])
```

```python
from openai import OpenAI

client = OpenAI()

completion = client.completions.create(model="davinci-002", prompt="Hello world")
chat_completion = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": "Hello world"}])
```

## Remap errors

```python
import openai

try:
    completion = openai.Completion.create(model="davinci-002", prompt="Hello world")
    chat_completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": "Hello world"}])
except openai.error.RateLimitError as err:
    pass
```

```python
import openai
from openai import OpenAI

client = OpenAI()

try:
    completion = client.completions.create(model="davinci-002", prompt="Hello world")
    chat_completion = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": "Hello world"}])
except openai.RateLimitError as err:
    pass
```
