# Copyright 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import copy
import platform
import os

from platformio.managers.platform import PlatformBase
from platformio.package.meta import PackageSpec
from platformio.platform.exception import UnknownBoard


class RaspberrypiPlatform(PlatformBase):

    __is_pico_core = False

    def is_embedded(self):
        return True
        
    def get_package(self, name, spec=None):
        # add "framework-arduino-pico" as alias to "framework-arduinopico"
        if name == "framework-arduino-pico":
            name = "framework-arduinopico"
        if spec and spec.name == "framework-arduino-pico":
            spec_dict = spec.as_dict()
            spec_dict.update("name", "framework-arduinopico")
            spec = PackageSpec(**spec_dict)
        return self.pm.get_package(spec or self.get_package_spec(name))

    def configure_default_packages(self, variables, targets):
        board = variables.get("board", "pico")
        build_core = variables.get(
            "board_build.core", self.board_config(variables.get("board")).get(
                "build.core", "arduino"))
        if build_core.lower() == "earlephilhower" or build_core.lower() == "rp2040":
            build_core = "pico"
            variables["board_build.core"] = build_core
            
            self.__is_pico_core = True
        
        if "arduino" in variables.get(
                "pioframework", []) and build_core != "arduino":
            core_framework = self.frameworks["arduino-%s" % build_core]
            core_framework_package = core_framework["package"]
            default_framework_package = self.frameworks["arduino"]["package"]
            
            self.frameworks["arduino"] = core_framework
            self.packages[core_framework_package]["optional"] = False
            self.packages[default_framework_package]["optional"] = True
        
        # configure J-LINK tool
        jlink_conds = [
            "jlink" in variables.get(option, "")
            for option in ("upload_protocol", "debug_tool")
        ]
        if variables.get("board"):
            board_config = self.board_config(variables.get("board"))
            jlink_conds.extend([
                "jlink" in board_config.get(key, "")
                for key in ("debug.default_tools", "upload.protocol")
            ])
        jlink_pkgname = "tool-jlink"
        if not any(jlink_conds) and jlink_pkgname in self.packages:
            del self.packages[jlink_pkgname]

        return PlatformBase.configure_default_packages(self, variables, targets)

    def get_boards(self, id_=None):
        try:
            framework_pico_dir = self.get_package_dir("framework-arduinopico")
        except KeyError:
            framework_pico_dir = None
            
        if framework_pico_dir and self.__is_pico_core:
            # framework-arduino-pico name for pico board is rpipico
            if id_ == "pico":
                id_ = "rpipico"
        
            # load boards from framework second, to overwrite
            # platform definitions with same name, if any
            PlatformBase.get_boards(self)
            result = self._get_boards_pico_dir(framework_pico_dir, id_)
        else:
            result = PlatformBase.get_boards(self, id_)
        
        if not result:
            return result
        if id_:
            return self._add_default_debug_tools(result)
        else:
            for key, value in result.items():
                result[key] = self._add_default_debug_tools(result[key])
        return result
        
    def _get_boards_pico_dir(self, framework_pico_dir, id_=None):
        current_boards_dir = self.config.get("platformio", "boards_dir", False)
        config_parser = self.config._parser
        if not config_parser.has_section("platformio"):
            config_parser.add_section("platformio")
        self.config.set("platformio", "boards_dir",
            os.path.join(framework_pico_dir, "tools", "json"))
            
        try:
            return PlatformBase.get_boards(self, id_)
        finally:
            if current_boards_dir:
                self.config.set("platformio", "boards_dir", current_boards_dir)

    def _add_default_debug_tools(self, board):
        debug = board.manifest.get("debug", {})
        upload_protocols = board.manifest.get("upload", {}).get(
            "protocols", [])
        if "tools" not in debug:
            debug["tools"] = {}

        for link in ("cmsis-dap", "jlink", "raspberrypi-swd"):
            if link not in upload_protocols or link in debug["tools"]:
                continue

            if link == "jlink":
                assert debug.get("jlink_device"), (
                    "Missed J-Link Device ID for %s" % board.id)
                debug["tools"][link] = {
                    "server": {
                        "package": "tool-jlink",
                        "arguments": [
                            "-singlerun",
                            "-if", "SWD",
                            "-select", "USB",
                            "-device", debug.get("jlink_device"),
                            "-port", "2331"
                        ],
                        "executable": ("JLinkGDBServerCL.exe"
                                       if platform.system() == "Windows" else
                                       "JLinkGDBServer")
                    },
                    "onboard": link in debug.get("onboard_tools", [])
                }
            else:
                openocd_target = debug.get("openocd_target")
                assert openocd_target, ("Missing target configuration for %s" % board.id)
                debug["tools"][link] = {
                    "server": {
                        "executable": "bin/openocd",
                        "package": "tool-openocd-raspberrypi",
                        "arguments": [
                            "-s", "$PACKAGE_DIR/share/openocd/scripts",
                            "-f", "interface/%s.cfg" % link,
                            "-f", "target/%s" % openocd_target
                        ]
                    }
                }

        board.manifest["debug"] = debug
        return board

    def configure_debug_session(self, debug_config):
        adapter_speed = debug_config.speed or "5000"
        
        server_options = debug_config.server or {}
        server_arguments = server_options.get("arguments", [])
        if "interface/cmsis-dap.cfg" in server_arguments:
            server_arguments.extend(
                ["-c", "adapter speed %s" % adapter_speed]
            )
        elif "jlink" in server_options.get("executable", "").lower():
            server_arguments.extend(
                ["-speed", adapter_speed]
            )
