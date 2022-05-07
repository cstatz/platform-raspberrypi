import sys
from os.path import join, isfile, isdir
import re
from SCons.Script import DefaultEnvironment


env = DefaultEnvironment()
board = env.BoardConfig()
platform = env.PioPlatform()
framework_dir = platform.get_package_dir("framework-arduinopico")

assert isdir(framework_dir)

# taken from https://github.com/maxgerhardt/platform-raspberrypi/blob/develop/builder/main.py
def convert_size_expression_to_int(expression):
    conversion_factors = {
        "M": 1024*1024,
        "MB": 1024*1024,
        "K": 1024,
        "KB": 1024,
        "B": 1,
        "": 1 # giving no conversion factor is factor 1.
    }
    # match <floating pointer number><conversion factor>.
    extract_regex = r'^((?:[0-9]*[.])?[0-9]+)([mkbMKB]*)$'
    res = re.findall(extract_regex, expression)
    # unparsable expression? Warning.
    if len(res) == 0:
        sys.stderr.write(
            "Error: Could not parse filesystem size expression '%s'."
            " Will treat as size = 0.\n" % str(expression))
        return 0
    # access first result
    number, factor = res[0]
    number = float(number)
    number *= conversion_factors[factor.upper()]
    return int(number)

# taken from https://github.com/maxgerhardt/platform-raspberrypi/blob/develop/builder/main.py
def fetch_fs_size(env):
    # follow generation formulas from makeboards.py for Earle Philhower core
    # given the total flash size, a user can specify
    # the amount for the filesystem (0MB, 2MB, 4MB, 8MB, 16MB)
    # via board_build.filesystem_size,
    # and we will calculate the flash size and eeprom size from that.
    flash_size = board.get("upload.maximum_size")
    #filesystem_size = board.get("build.filesystem_size", "0MB")
    filesystem_size = "0MB"
    filesystem_size_int = convert_size_expression_to_int(filesystem_size)

    maximum_size = flash_size - 4096 - filesystem_size_int

    print("Flash size: %.2fMB" % (flash_size / 1024.0 / 1024.0))
    print("Sketch size: %.2fMB" % (maximum_size / 1024.0 / 1024.0))
    print("Filesystem size: %.2fMB" % (filesystem_size_int / 1024.0 / 1024.0))

    flash_length = maximum_size
    eeprom_start = 0x10000000 + flash_size - 4096
    fs_start = 0x10000000 + flash_size - 4096 - filesystem_size_int
    fs_end = 0x10000000 + flash_size - 4096

    if maximum_size <= 0:
        sys.stderr.write(
            "Error: Filesystem too large for given flash. "
            "Can at max be flash size - 4096 bytes. "
            "Available sketch size with current "
            "config would be %d bytes.\n" % maximum_size)
        sys.stderr.flush()
        env.Exit(-1)

    env["PICO_FLASH_LENGTH"] = flash_length
    env["PICO_EEPROM_START"] = eeprom_start
    env["FS_START"] = fs_start
    env["FS_END"] = fs_end
    # LittleFS configuration parameters taken from
    # https://github.com/earlephilhower/arduino-pico-littlefs-plugin/blob/master/src/PicoLittleFS.java
    env["FS_PAGE"] = 256
    env["FS_BLOCK"] = 4096

    print("Maximium size: %d Flash Length: %d "
        "EEPROM Start: %d Filesystem start %d "
        "Filesystem end %s" % 
        (maximum_size,flash_length, eeprom_start, fs_start, fs_end))


# adjust variant naming
variant_key = "build.arduino.earlephilhower.variant"
variant = board.get(variant_key,
    board.get("build.variant", "").replace("RASPBERRY_PI_PICO", "rpipico"))
board.update(variant_key, variant)

# This platform does not make use of LittleFS Filesystem Uploader
# Define dummy function to fullfill the build script's requirements
env["fetch_fs_size"] = lambda env : None
fetch_fs_size(env)


# load build script from arduino-pico framework
build_script = join(
    platform.get_package_dir("framework-arduino-pico"),
    "tools", "platformio-build.py")


# Ignore TinyUSB automatically if not active without requiring ldf_mode = chain+
cpp_defines = env.Flatten(env.get("CPPDEFINES", []))
if not "USE_TINYUSB" in cpp_defines:
    env_section = "env:" + env["PIOENV"]
    ignored_libs = platform.config.get(
            env_section, "lib_ignore", []
        )
    if not "Adafruit TinyUSB Library" in ignored_libs:
        ignored_libs.append("Adafruit TinyUSB Library")
    platform.config.set(
            env_section, "lib_ignore", ignored_libs
        )   

assert isfile(build_script)
env.SConscript(build_script)
