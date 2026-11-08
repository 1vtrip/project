cmake_minimum_required(VERSION 3.15)
project(schedule_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ВНИМАНИЕ: cpr/curl убраны из зависимостей — их сборка из исходников
# под MinGW ломалась на баге детекта неблокирующих сокетов в curl.
# Вместо этого HTTP-запросы реализованы напрямую через WinHTTP —
# это часть Windows SDK, уже скомпилирована, ничего собирать не нужно.
# Из-за этого модуль становится Windows-only (WinHTTP — не кроссплатформенный
# API). Если понадобится Linux/macOS — возвращаемся к curl/cpr отдельно.

include(FetchContent)

FetchContent_Declare(
  json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG        v3.11.3
)
FetchContent_MakeAvailable(json)

add_executable(schedule_engine main1.cpp)
target_link_libraries(schedule_engine PRIVATE nlohmann_json::nlohmann_json)

if(WIN32)
  target_link_libraries(schedule_engine PRIVATE winhttp)
endif()
