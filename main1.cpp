// schedule_engine — C++ Data Engine для Telegram-бота расписания БГУИР.
//
// HTTP-запросы выполняются через WinHTTP (часть Windows SDK), а не через
// curl/cpr — это сделано, чтобы не бороться со сборкой curl из исходников
// под MinGW. Из-за этого модуль Windows-only. Если команде понадобится
// Linux/macOS — нужно будет вернуться к curl/cpr (или libcurl через
// системный пакетный менеджер) и переписать только функцию HttpGet.
//
// Контракт с Python-слоем (integration/ipc_bridge.py):
//   Запуск:  schedule_engine.exe <номер_группы>
//
//   Вывод в stdout — ровно один из трёх вариантов:
//     1) Одна или несколько строк занятий, формат (поля разделены "|"):
//        startTime|endTime|subjectFullName|lessonType|auditories|teachers|subgroup|note
//        - auditories и teachers, если их несколько — через запятую внутри поля
//        - subgroup: "0" если лекция/занятие общее на всю группу, иначе 1 или 2
//        - note может быть пустым
//     2) Строка "NO_LESSONS" — если на сегодня пар по расписанию нет.
//     3) Ничего в stdout, если произошла ошибка — тогда см. п.3 ниже.
//
//   При ошибке (сеть недоступна, группа не найдена, не распарсился JSON):
//     - в stdout ничего не печатается,
//     - в stderr печатается "ERROR: <описание>",
//     - процесс завершается с кодом возврата 1.
//   Python-слой должен проверять return code перед чтением stdout.
//
// Допущения по схеме JSON (не проверены боевым запросом, см. NOTES.md):
//   - структура ответа https://iis.bsuir.by/api/v1/schedule?studentGroup=XXXXXX
//   - отдельный эндпоинт /api/v1/schedule/current-week, возвращающий
//     текущую учебную неделю (1-4) простым текстом.
//   Если эндпоинт недели недоступен/изменился — код сам считает неделю
//   от даты начала семестра (1 сентября текущего года), это fallback.

#ifdef _WIN32
#include <windows.h>
#include <winhttp.h>
#pragma comment(lib, "winhttp.lib")
#endif

#include <nlohmann/json.hpp>

#include <array>
#include <chrono>
#include <cstdlib>
#include <ctime>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

using json = nlohmann::json;

namespace {

// Порядок дней как в API (с заглавной буквы, как отдаёт БГУИР).
const std::array<std::string, 7> kRussianDays = {
    "Воскресенье", "Понедельник", "Вторник", "Среда",
    "Четверг",     "Пятница",     "Суббота"
};

struct HttpResponse {
    bool ok = false;
    int status = 0;
    std::string body;
};

// Переводит обычную ASCII-строку (номер группы, путь запроса) в wide string.
// Пригодно только для ASCII-содержимого (цифры/латиница), чего достаточно
// для номеров групп и путей API.
std::wstring ToWide(const std::string& s) {
    return std::wstring(s.begin(), s.end());
}

// Выполняет HTTPS GET к host+path через WinHTTP. Тело ответа возвращается
// как сырые байты в std::string (UTF-8, как его прислал сервер) — поэтому
// дальнейший json::parse получает корректный UTF-8 без доп. преобразований.
HttpResponse HttpGet(const std::wstring& host, const std::wstring& path, int timeoutMs) {
    HttpResponse result;
#ifdef _WIN32
    HINTERNET hSession = WinHttpOpen(L"schedule_engine/1.0",
                                      WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                      WINHTTP_NO_PROXY_NAME,
                                      WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) {
        std::cerr << "ERROR: WinHttpOpen failed, GetLastError=" << GetLastError() << std::endl;
        return result;
    }

    WinHttpSetTimeouts(hSession, timeoutMs, timeoutMs, timeoutMs, timeoutMs);

    HINTERNET hConnect = WinHttpConnect(hSession, host.c_str(),
                                         INTERNET_DEFAULT_HTTPS_PORT, 0);
    if (!hConnect) {
        std::cerr << "ERROR: WinHttpConnect failed, GetLastError=" << GetLastError() << std::endl;
        WinHttpCloseHandle(hSession);
        return result;
    }

    HINTERNET hRequest = WinHttpOpenRequest(
        hConnect, L"GET", path.c_str(), nullptr, WINHTTP_NO_REFERER,
        WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE);
    if (!hRequest) {
        std::cerr << "ERROR: WinHttpOpenRequest failed, GetLastError=" << GetLastError() << std::endl;
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return result;
    }

    BOOL sent = WinHttpSendRequest(hRequest, WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                                    WINHTTP_NO_REQUEST_DATA, 0, 0, 0);
    if (!sent) {
        std::cerr << "ERROR: WinHttpSendRequest failed, GetLastError=" << GetLastError() << std::endl;
    }
    BOOL received = sent && WinHttpReceiveResponse(hRequest, nullptr);
    if (sent && !received) {
        std::cerr << "ERROR: WinHttpReceiveResponse failed, GetLastError=" << GetLastError() << std::endl;
    }

    if (received) {
        DWORD statusCode = 0;
        DWORD statusSize = sizeof(statusCode);
        WinHttpQueryHeaders(
            hRequest, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
            WINHTTP_HEADER_NAME_BY_INDEX, &statusCode, &statusSize,
            WINHTTP_NO_HEADER_INDEX);
        result.status = static_cast<int>(statusCode);

        std::string body;
        DWORD dwSize = 0;
        do {
            dwSize = 0;
            if (!WinHttpQueryDataAvailable(hRequest, &dwSize)) break;
            if (dwSize == 0) break;
            std::vector<char> buffer(dwSize);
            DWORD dwDownloaded = 0;
            if (!WinHttpReadData(hRequest, buffer.data(), dwSize, &dwDownloaded)) break;
            body.append(buffer.data(), dwDownloaded);
        } while (dwSize > 0);

        result.body = body;
        result.ok = true;
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
#else
    (void)host;
    (void)path;
    (void)timeoutMs;
#endif
    return result;
}

struct TodayInfo {
    std::string dayName;
    int year;
    int month;
    int day;
};

TodayInfo GetToday() {
    std::time_t t = std::time(nullptr);
    std::tm local_tm{};
#if defined(_WIN32)
    localtime_s(&local_tm, &t);
#else
    localtime_r(&t, &local_tm);
#endif
    TodayInfo info;
    info.dayName = kRussianDays[local_tm.tm_wday];
    info.year = local_tm.tm_year + 1900;
    info.month = local_tm.tm_mon + 1;
    info.day = local_tm.tm_mday;
    return info;
}

// Fallback-вычисление номера учебной недели (1-4), если API-эндпоинт
// текущей недели недоступен. Отсчёт — от 1 сентября текущего учебного года.
int ComputeFallbackWeek() {
    std::time_t now = std::time(nullptr);
    std::tm local_tm{};
#if defined(_WIN32)
    localtime_s(&local_tm, &now);
#else
    localtime_r(&now, &local_tm);
#endif

    int currentYear = local_tm.tm_year + 1900;
    int startYear = (local_tm.tm_mon + 1 >= 9) ? currentYear : currentYear - 1;

    std::tm startTm{};
    startTm.tm_year = startYear - 1900;
    startTm.tm_mon = 8;  // сентябрь (0-indexed)
    startTm.tm_mday = 1;
    startTm.tm_hour = 0;
    startTm.tm_min = 0;
    startTm.tm_sec = 0;
    startTm.tm_isdst = -1;
    std::time_t startTime = std::mktime(&startTm);

    double diffSeconds = std::difftime(now, startTime);
    if (diffSeconds < 0) diffSeconds = 0;
    long daysSinceStart = static_cast<long>(diffSeconds / 86400);
    long weekIndex = (daysSinceStart / 7) % 4;
    return static_cast<int>(weekIndex) + 1;
}

// Пытается получить текущую неделю напрямую у API БГУИР.
// Возвращает -1, если не удалось (тогда вызывающий код должен
// использовать ComputeFallbackWeek()).
int FetchCurrentWeekFromApi() {
    HttpResponse r = HttpGet(L"iis.bsuir.by", L"/api/v1/schedule/current-week", 5000);
    if (!r.ok || r.status != 200 || r.body.empty()) return -1;

    std::string text = r.body;
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r' || text.back() == ' ')) {
        text.pop_back();
    }
    try {
        int week = std::stoi(text);
        if (week >= 1 && week <= 4) return week;
    } catch (...) {
        try {
            json j = json::parse(text);
            if (j.is_number_integer()) {
                int week = j.get<int>();
                if (week >= 1 && week <= 4) return week;
            }
            if (j.contains("week") && j["week"].is_number_integer()) {
                int week = j["week"].get<int>();
                if (week >= 1 && week <= 4) return week;
            }
        } catch (...) {
            return -1;
        }
    }
    return -1;
}

std::string JoinStrings(const std::vector<std::string>& items, const std::string& sep) {
    std::string out;
    for (size_t i = 0; i < items.size(); ++i) {
        if (i) out += sep;
        out += items[i];
    }
    return out;
}

std::string TeacherFullName(const json& employee) {
    std::string last = employee.value("lastName", "");
    std::string first = employee.value("firstName", "");
    std::string middle = employee.value("middleName", "");
    std::string result = last;
    if (!first.empty()) {
        result += " " + first.substr(0, 1) + ".";
        if (!middle.empty()) result += middle.substr(0, 1) + ".";
    }
    return result;
}

// Находит массив занятий на нужный день внутри JSON-ответа. Поддерживает
// два варианта структуры: {"schedules": {"День": [...]}} и плоский
// {"День": [...]} на верхнем уровне — на случай расхождений в версии API.
const json* FindDayLessons(const json& root, const std::string& dayName) {
    if (root.contains("schedules") && root["schedules"].is_object()) {
        const json& schedules = root["schedules"];
        if (schedules.contains(dayName) && schedules[dayName].is_array()) {
            return &schedules[dayName];
        }
        return nullptr;
    }
    if (root.contains(dayName) && root[dayName].is_array()) {
        return &root[dayName];
    }
    return nullptr;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 2 || std::string(argv[1]).empty()) {
        std::cerr << "ERROR: group number not provided (usage: schedule_engine <group>)" << std::endl;
        return 1;
    }
    const std::string group = argv[1];

    TodayInfo today = GetToday();

    int currentWeek = FetchCurrentWeekFromApi();
    if (currentWeek == -1) {
        currentWeek = ComputeFallbackWeek();
    }

    std::wstring path = L"/api/v1/schedule?studentGroup=" + ToWide(group);
    HttpResponse resp = HttpGet(L"iis.bsuir.by", path, 8000);

    if (!resp.ok) {
        std::cerr << "ERROR: HTTP request to iis.bsuir.by failed (network/WinHTTP error)" << std::endl;
        return 1;
    }
    if (resp.status != 200) {
        std::cerr << "ERROR: API returned status " << resp.status
                  << " for group " << group << std::endl;
        return 1;
    }

    json root;
    try {
        root = json::parse(resp.body);
    } catch (const std::exception& e) {
        std::cerr << "ERROR: failed to parse JSON response: " << e.what() << std::endl;
        return 1;
    }

    const json* lessonsToday = FindDayLessons(root, today.dayName);
    if (lessonsToday == nullptr) {
        std::cout << "NO_LESSONS" << std::endl;
        return 0;
    }

    bool printedAny = false;
    for (const auto& lesson : *lessonsToday) {
        if (lesson.contains("weekNumber") && lesson["weekNumber"].is_array()) {
            bool matchesWeek = false;
            for (const auto& w : lesson["weekNumber"]) {
                if (w.is_number_integer() && w.get<int>() == currentWeek) {
                    matchesWeek = true;
                    break;
                }
            }
            if (!matchesWeek) continue;
        }

        std::string startTime = lesson.value("startLessonTime", "");
        std::string endTime = lesson.value("endLessonTime", "");
        std::string subject = lesson.value("subjectFullName", lesson.value("subject", ""));
        std::string lessonType = lesson.value("lessonTypeAbbrev", "");
        std::string note = lesson.value("note", "");
        int subgroup = lesson.value("numSubgroup", 0);

        std::vector<std::string> auditories;
        if (lesson.contains("auditories") && lesson["auditories"].is_array()) {
            for (const auto& a : lesson["auditories"]) {
                if (a.is_string()) auditories.push_back(a.get<std::string>());
            }
        }

        std::vector<std::string> teachers;
        if (lesson.contains("employees") && lesson["employees"].is_array()) {
            for (const auto& emp : lesson["employees"]) {
                std::string name = TeacherFullName(emp);
                if (!name.empty()) teachers.push_back(name);
            }
        }

        std::ostringstream line;
        line << startTime << "|" << endTime << "|" << subject << "|" << lessonType << "|"
             << JoinStrings(auditories, ",") << "|" << JoinStrings(teachers, ",") << "|"
             << subgroup << "|" << note;

        std::cout << line.str() << std::endl;
        printedAny = true;
    }

    if (!printedAny) {
        std::cout << "NO_LESSONS" << std::endl;
    }

    return 0;
}
