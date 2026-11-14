<?php
// =====================================================================
// Кросс Автопостинг (@se14808890_1_bot) — webhook-обработчик, этап 1.
//
// ШАБЛОН БЕЗ СЕКРЕТОВ ({{TOKEN}} и {{SECRET}} заменяются при генерации
// рабочего файла local/hosting/bot2_webhook.php — он в git не попадает).
//
// Логика (docs/bot2-roadmap.md, этап 1 «Старт + автоответ»):
//   bot_started      -> приветствие + inline-меню (кнопки);
//   message_callback -> обработка кнопок (POST /answers + ответ);
//   message_created  -> автоответы по ключевым словам + fallback.
//
// Требования хостинга: PHP 8.x + cURL, HTTPS на домене.
// MAX шлёт события POST-запросом на https://<домен>/<путь>?s=<SECRET>.
// =====================================================================

declare(strict_types=1);

const BOT_TOKEN = '{{TOKEN}}';
const SECRET    = '{{SECRET}}';
const API       = 'https://platform-api2.max.ru';
const LOG_FILE  = __DIR__ . '/bot2_webhook.log';

// --- тексты этапа 1 ------------------------------------------------------

const WELCOME = "Привет! Я **Кросс Автопостинг** — помощник авторов каналов MAX.\n\n"
    . "Сейчас я на ранней стадии, но уже скоро научусь:\n"
    . "✍️ вычитывать тексты перед публикацией\n"
    . "⏰ публиковать посты по расписанию\n"
    . "🔁 переносить посты из Telegram в MAX\n\n"
    . "Нажмите кнопку ниже или напишите «возможности» — расскажу подробнее.";

const CAPABILITIES = "**Что я умею и чему учусь**\n\n"
    . "🟢 Сейчас:\n"
    . "• знакомство и помощь с навигацией\n\n"
    . "🔧 В разработке (дорожная карта):\n"
    . "• этап 2 — вычитка текста: пришлёте черновик — верну исправленный вариант\n"
    . "• этап 3–4 — анализ канала и подбор SEO-ядра\n"
    . "• этап 5 — отложенный постинг по расписанию\n"
    . "• этап 6 — кросспостинг Telegram ↔ MAX\n\n"
    . "О новых этапах сообщу здесь же — бот умеет писать первым.";

const FALLBACK = "Я пока учусь и понимаю только простые команды: «возможности», "
    . "«старт», «помощь». Вычитка и постинг появятся скоро — напишите "
    . "«возможности», чтобы посмотреть, что в разработке.";

const BUTTONS = [
    [['type' => 'callback', 'text' => 'Возможности бота', 'payload' => 'menu.capabilities']],
    [['type' => 'callback', 'text' => 'С начала', 'payload' => 'menu.welcome']],
];

const MENU = [
    'menu.capabilities' => CAPABILITIES,
    'menu.welcome'      => WELCOME,
];

const KEYWORDS = [
    ['возможност', 'что умеешь', 'умеешь'],
    ['старт', 'привет', 'здравствуй', 'начать'],
    ['помощь', 'help'],
];

// --- служебное ------------------------------------------------------------

function logline(string $msg): void
{
    @file_put_contents(LOG_FILE, gmdate('Y-m-d H:i:s') . " | " . $msg . "\n", FILE_APPEND);
}

/** @return array{code:int,body:array|mixed} */
function api(string $method, string $path, ?array $payload = null): array
{
    $ch = curl_init(API . $path);
    $headers = ['Authorization: ' . BOT_TOKEN, 'User-Agent: curl/8.13.0'];
    if ($payload !== null) {
        $headers[] = 'Content-Type: application/json';
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload, JSON_UNESCAPED_UNICODE));
    }
    curl_setopt_array($ch, [
        CURLOPT_CUSTOMREQUEST  => $method,
        CURLOPT_HTTPHEADER     => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => 20,
    ]);
    $body = curl_exec($ch);
    $code = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $json = is_string($body) ? json_decode($body, true) : [];
    if ($code !== 200) {
        logline("API FAIL $method $path -> $code " . substr((string)$body, 0, 200));
    }
    return ['code' => $code, 'body' => is_array($json) ? $json : []];
}

function send_text(int $chatId, string $text): bool
{
    $r = api('POST', '/messages?chat_id=' . $chatId, [
        'text'        => $text,
        'format'      => 'markdown',
        'attachments' => [['type' => 'inline_keyboard', 'payload' => ['buttons' => BUTTONS]]],
    ]);
    usleep(600000); // лимит 2 сообщения/сек на чат
    return $r['code'] === 200;
}

// --- точка входа ----------------------------------------------------------

// 1) секрет в query — защита от поддельных вызовов
if (!isset($_GET['s']) || !hash_equals(SECRET, (string)$_GET['s'])) {
    http_response_code(403);
    exit('forbidden');
}

// 2) читаем событие
$raw = file_get_contents('php://input');
$upd = json_decode((string)$raw, true);
if (!is_array($upd)) {
    http_response_code(400);
    exit('bad payload');
}

// 3) отдаём 200 сразу, обработку — в лог, чтобы MAX не ретраил
http_response_code(200);
header('Content-Type: text/plain');
echo 'ok';

$type    = (string)($upd['update_type'] ?? '');
$chatId  = (int)($upd['chat_id'] ?? 0);
logline("EVENT $type chat=$chatId");

switch ($type) {
    case 'bot_started':
        send_text($chatId, WELCOME);
        break;

    case 'message_callback':
        $payload    = (string)($upd['callback']['payload'] ?? '');
        $callbackId = (string)($upd['callback']['callback_id'] ?? '');
        if (isset(MENU[$payload]) && $callbackId !== '') {
            api('POST', '/answers', [
                'callback_id' => $callbackId,
                'message'     => ['text' => 'Открываю…', 'format' => 'markdown'],
            ]);
            usleep(600000);
            send_text($chatId, MENU[$payload]);
        }
        break;

    case 'message_created':
        $text = trim((string)($upd['message']['body']['text'] ?? ''));
        if ($text === '') {
            break;
        }
        $low = mb_strtolower($text);
        $reply = FALLBACK;
        foreach (KEYWORDS as $needles) {
            foreach ($needles as $n) {
                if (mb_stripos($low, $n) !== false) {
                    $reply = ($n === 'старт' || $n === 'привет' || $n === 'здравствуй' || $n === 'начать')
                        ? WELCOME : CAPABILITIES;
                    break 2;
                }
            }
        }
        send_text($chatId, $reply);
        break;

    case 'bot_stopped':
    case 'dialog_removed':
        // ничего не делаем
        break;

    default:
        logline("UNHANDLED $type: " . substr((string)$raw, 0, 300));
}
