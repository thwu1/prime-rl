import lit.formats
import os

config.name = "IR-Opt"
config.test_format = lit.formats.ShTest(True)
config.suffixes = ['.test']
config.test_source_root = os.path.dirname(__file__)

config.substitutions.append(('%ir-opt', 'python3 /app/tools/ir_opt'))
