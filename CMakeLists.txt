cmake_minimum_required(VERSION 3.10)
project(show LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# pkg-config
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED gstreamer-1.0 gstreamer-app-1.0)

# ---- CUDA ----
find_package(CUDA REQUIRED)
message(STATUS "CUDA found: ${CUDA_TOOLKIT_ROOT_DIR} (${CUDA_VERSION})")

# ---- DeepStream ----
set(DEEPSTREAM_PATH "/opt/nvidia/deepstream/deepstream-7.1")
if(NOT EXISTS ${DEEPSTREAM_PATH})
    file(GLOB DS_DIRS /opt/nvidia/deepstream/deepstream-*)
    if(DS_DIRS)
        list(GET DS_DIRS 0 DEEPSTREAM_PATH)
    endif()
endif()
message(STATUS "DeepStream path: ${DEEPSTREAM_PATH}")

if(NOT EXISTS ${DEEPSTREAM_PATH})
    message(FATAL_ERROR "DeepStream not found at ${DEEPSTREAM_PATH}. "
                        "Install DeepStream or set DEEPSTREAM_PATH.")
endif()

set(DEEPSTREAM_INCLUDE_DIRS "${DEEPSTREAM_PATH}/sources/includes")
set(DEEPSTREAM_LIB_DIR "${DEEPSTREAM_PATH}/lib")

if(NOT EXISTS ${DEEPSTREAM_INCLUDE_DIRS})
    message(FATAL_ERROR "DeepStream includes not found: ${DEEPSTREAM_INCLUDE_DIRS}")
endif()

# ---- MVS (Hikvision SDK) ----
set(MVS_PATH "/opt/MVS")
set(MVS_INCLUDE_DIR "${MVS_PATH}/include")

# Detect architecture for MVS lib path
if(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64")
    set(MVS_LIB_DIR "${MVS_PATH}/lib/aarch64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64")
    set(MVS_LIB_DIR "${MVS_PATH}/lib/x86_64")
else()
    set(MVS_LIB_DIR "${MVS_PATH}/lib/aarch64")
endif()

if(NOT EXISTS ${MVS_INCLUDE_DIR})
    message(WARNING "MVS SDK include not found at ${MVS_INCLUDE_DIR}. "
                    "Camera features will not compile.")
endif()

link_directories(${DEEPSTREAM_LIB_DIR} ${MVS_LIB_DIR})

# ---- Executable ----
add_executable(${PROJECT_NAME} main.cpp)

add_library(nvdsinfer_custom_fd_lpd SHARED nvdsinfer_custom_fd_lpd.cpp)

target_include_directories(nvdsinfer_custom_fd_lpd PRIVATE
    ${DEEPSTREAM_INCLUDE_DIRS}
    ${CUDA_INCLUDE_DIRS}
    ${CUDA_TOOLKIT_ROOT_DIR}/include
)

target_link_libraries(nvdsinfer_custom_fd_lpd PRIVATE
    nvds_infer
)

target_include_directories(${PROJECT_NAME} PRIVATE
    ${GST_INCLUDE_DIRS}
    ${DEEPSTREAM_INCLUDE_DIRS}
    ${MVS_INCLUDE_DIR}
    ${CUDA_TOOLKIT_INCLUDE}
)

target_link_libraries(${PROJECT_NAME} PRIVATE
    ${GST_LIBRARIES}
    ${CUDA_LIBRARIES}
    nvdsgst_meta
    nvds_meta
    nvdsgst_helper
    nvds_utils
    MvCameraControl
    pthread
    dl
)

# ---- Copy configs to build dir ----
add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/configs/pgie_config_fd_lpd.txt
        $<TARGET_FILE_DIR:${PROJECT_NAME}>/
)
