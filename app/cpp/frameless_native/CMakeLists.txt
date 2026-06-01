cmake_minimum_required(VERSION 3.21)
project(FramelessNative LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 6.6 REQUIRED COMPONENTS Core Gui Qml Quick)

get_filename_component(FRAMELESS_NATIVE_PROJECT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../.." ABSOLUTE)
set(QWINDOWKIT_SOURCE_DIR "${FRAMELESS_NATIVE_PROJECT_ROOT}/third_party/qwindowkit" CACHE PATH "QWindowKit source directory")

if(NOT EXISTS "${QWINDOWKIT_SOURCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "QWindowKit source not found: ${QWINDOWKIT_SOURCE_DIR}")
endif()

set(QWINDOWKIT_BUILD_STATIC ON CACHE BOOL "" FORCE)
set(QWINDOWKIT_BUILD_QUICK ON CACHE BOOL "" FORCE)
set(QWINDOWKIT_BUILD_WIDGETS OFF CACHE BOOL "" FORCE)
set(QWINDOWKIT_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(QWINDOWKIT_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(QWINDOWKIT_BUILD_DOCUMENTATIONS OFF CACHE BOOL "" FORCE)
set(QWINDOWKIT_INSTALL OFF CACHE BOOL "" FORCE)
# The project-root b.bat builds this module twice:
# - system: QWindowKit keeps Windows system borders for the trusted Win11 path.
# - custom: QWindowKit system borders are disabled for Win10/VM custom chrome.

add_subdirectory(${QWINDOWKIT_SOURCE_DIR} ${CMAKE_BINARY_DIR}/qwindowkit)

if(NOT TARGET QWindowKit::Quick)
    message(FATAL_ERROR "QWindowKit::Quick target not found.")
endif()

if(NOT DEFINED FRAMELESS_NATIVE_QML_OUTPUT_DIR)
    set(FRAMELESS_NATIVE_QML_OUTPUT_DIR "${FRAMELESS_NATIVE_PROJECT_ROOT}/app/native/prebuilt/win32-x64-py310-qt6.11/qml")
endif()

qt_add_qml_module(FramelessNative
    URI FramelessNative
    VERSION 1.0
    RESOURCE_PREFIX "/qt/qml/"
    OUTPUT_DIRECTORY "${FRAMELESS_NATIVE_QML_OUTPUT_DIR}/FramelessNative"
    SOURCES
        src/external_shadow_controller.h
        src/external_shadow_controller.cpp
        src/native_window_agent.h
        src/native_window_agent.cpp
)

set_target_properties(FramelessNative PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${FRAMELESS_NATIVE_QML_OUTPUT_DIR}/FramelessNative"
    LIBRARY_OUTPUT_DIRECTORY "${FRAMELESS_NATIVE_QML_OUTPUT_DIR}/FramelessNative"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
)

target_include_directories(FramelessNative PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${QWINDOWKIT_SOURCE_DIR}/src/core
    ${QWINDOWKIT_SOURCE_DIR}/src/quick
)

target_link_libraries(FramelessNative PRIVATE
    QWindowKit::Quick
    Qt6::Core
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
)

if(WIN32)
    target_link_libraries(FramelessNative PRIVATE dwmapi user32 gdi32)
endif()
