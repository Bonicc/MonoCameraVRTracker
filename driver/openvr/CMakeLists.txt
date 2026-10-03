cmake_minimum_required(VERSION 3.21)
project(MonoCameraSteamVRDriver VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
include(CTest)

if(BUILD_TESTING)
    add_executable(protocol_test ../../tests/native/protocol_test.cpp)
    target_include_directories(protocol_test PRIVATE src)
    add_test(NAME udp_protocol COMMAND protocol_test "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/native/valid_packet.hex")
endif()

if(WIN32)
    if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
        message(FATAL_ERROR "SteamVR driver requires a 64-bit compiler; use Visual Studio -A x64 or x64 MinGW.")
    endif()
    include(FetchContent)
    if(BUILD_TESTING)
        add_executable(udp_receiver_test ../../tests/native/udp_receiver_test.cpp)
        target_include_directories(udp_receiver_test PRIVATE src)
        target_link_libraries(udp_receiver_test PRIVATE ws2_32)
        add_test(NAME udp_receiver COMMAND udp_receiver_test "${CMAKE_CURRENT_SOURCE_DIR}/../../tests/native/valid_packet.hex")
    endif()
    # Official Valve OpenVR v2.12.14, pinned by commit and file checksum.
    # Driver interfaces/context helpers are header-only; no application openvr_api calls.
    FetchContent_Declare(openvr_header
        URL https://raw.githubusercontent.com/ValveSoftware/openvr/91825305130f446f82054c1ec3d416321ace0072/headers/openvr_driver.h
        URL_HASH SHA256=2e3425f0db51c9918092f1e9eb59aad9da662d3f9d404ef66030c89b0d82e6ef
        DOWNLOAD_NO_EXTRACT TRUE
    )
    FetchContent_MakeAvailable(openvr_header)
    add_library(driver_monocameravrtracker SHARED src/driver.cpp)
    target_include_directories(driver_monocameravrtracker PRIVATE src)
    target_include_directories(driver_monocameravrtracker SYSTEM PRIVATE "${openvr_header_SOURCE_DIR}")
    target_link_libraries(driver_monocameravrtracker PRIVATE ws2_32)
    target_compile_definitions(driver_monocameravrtracker PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
    set(package_dir "${CMAKE_BINARY_DIR}/monocameravrtracker")
    set_target_properties(driver_monocameravrtracker PROPERTIES
        PREFIX ""
        OUTPUT_NAME "driver_monocameravrtracker"
        RUNTIME_OUTPUT_DIRECTORY "${package_dir}/bin/win64"
        RUNTIME_OUTPUT_DIRECTORY_DEBUG "${package_dir}/bin/win64"
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${package_dir}/bin/win64"
        RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO "${package_dir}/bin/win64"
        RUNTIME_OUTPUT_DIRECTORY_MINSIZEREL "${package_dir}/bin/win64"
    )
    if(MSVC)
        target_compile_options(driver_monocameravrtracker PRIVATE /W4 /permissive-)
    elseif(MINGW)
        target_compile_options(driver_monocameravrtracker PRIVATE -Wall -Wextra)
        target_link_options(driver_monocameravrtracker PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
    add_custom_command(TARGET driver_monocameravrtracker POST_BUILD
        COMMAND "${CMAKE_COMMAND}" -E copy_directory
            "${CMAKE_CURRENT_SOURCE_DIR}/monocameravrtracker" "${package_dir}"
        COMMAND "${CMAKE_COMMAND}" -E copy
            "${CMAKE_CURRENT_SOURCE_DIR}/register-driver.ps1" "${package_dir}/register-driver.ps1"
        COMMAND "${CMAKE_COMMAND}" -E copy
            "${CMAKE_CURRENT_SOURCE_DIR}/../../LICENSE" "${package_dir}/LICENSE.txt"
    )
else()
    message(STATUS "Only portable protocol tests are built; the SteamVR DLL targets Windows x64.")
endif()
