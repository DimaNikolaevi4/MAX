<?php
// =====================================================================
// Личный новостной бот (@se14808890_bot, AI Now) — webhook-обработчик.
//
// Порт логики roles/newsbot/src/digest_bot.py на PHP по плану
// docs/bot-hosting-webhook-plan.md (решение владельца 12.11.2026).
// ШАБЛОН БЕЗ СЕКРЕТОВ: {{TOKEN}}, {{SECRET}}, {{OWNER_USER_ID}},
// {{OWNER_CHAT_ID}} заменяются при генерации локального файла
// local/hosting/bot1_webhook.php (в git не попадает).
//
// Что делает (AUTO_REPLY = True — переезд на хостинг, всегда на связи):
//   bot_started       -> фиксация в реестре + приветствие GREETING_TEXT;
//   message_created /
//   message_edited    -> личка: «стоп» / бриф (темы:…) / обращение
//                        (квитанция + копия владельцу); сообщения
//                        владельца «отв <id> <текст>» — ручные ответы;
//   user_added /
//   user_removed      -> чёрный журнал (каналы, chat_id < 0) для снимка;
//   канальные события -> только в журнал, без реакций.
//
// Файлы (вне webroot, из HTTP недоступны): DATA_DIR —
//   pnews_registry.json (реестр, общий с ПК-инструментами),
//   pnews_churn.jsonl   (журнал подписок/отписок),
//   bot1_webhook.log    (журнал работы).
//
// MAX шлёт события на https://0s3.ru/bot1/bot1_webhook.php
//   секрет — в заголовке X-Max-Bot-Api-Secret (основная проверка)
//   и дублируется в query ?s= (резерв, совместимо с имитатором).
// Ответ: 200 сразу (fastcgi_finish_request), обработка — после.
// =====================================================================

declare(strict_types=1);
mb_internal_encoding('UTF-8');

const BOT_TOKEN = '{{TOKEN}}';
const SECRET    = '{{SECRET}}';

// Владелец: user_id и chat_id его диалога с ботом
// (roles/newsbot/TASK.md: chat_id диалога НЕ равен user_id).
const OWNER_USER_ID = '{{OWNER_USER_ID}}';
const OWNER_CHAT_ID = {{OWNER_CHAT_ID}};

// Данные вне webroot: public_html/bot1 -> /0s3/bot1-data
const DATA_DIR    = __DIR__ . '/../../bot1-data';
const REG_PATH    = DATA_DIR . '/pnews_registry.json';
const CHURN_PATH  = DATA_DIR . '/pnews_churn.jsonl';
const LOG_PATH    = DATA_DIR . '/bot1_webhook.log';

const API = 'https://platform-api2.max.ru';
const CA_FILE = __DIR__ . '/russian_ca_bundle.pem';

// ---------- тексты (дословно из digest_bot.py, владелец 11.11.2026) -----

const GREETING_TEXT =
    "Я бот — волшебная палочка. Как и мой хозяин, могу почти всё. "
    . "Сейчас помогаю ему вести каналы:\n\n"
    . "• «Забавное» — https://max.ru/channel_zabava\n"
    . "• «Новости технологий ИИ, нейросетей и инноваций» — https://max.ru/channel_na100\n"
    . "• «AI» — https://max.ru/channel_ainow\n\n"
    . "Если у вас есть вопрос или нужна помощь — особенно в сфере IT — напишите "
    . "здесь. Единственное, что нам не подвластно, — время, а помощь нужна "
    . "многим. Но если напишете что-то интересное, обязательно ответим и "
    . "постараемся помочь.";

const ACK_TEXT =
    "✅ Ваше сообщение принято. Отвечаем по мере прочтения — "
    . "как только освободимся, ответим здесь же.";

const FORM_HINT =
    "Скопируйте и допишите:\n"
    . "темы: ИИ, нейросети, робототехника\n"
    . "частота: раз в день\n"
    . "источники: (не обязательно)";

// ---------- служебное ----------------------------------------------------

function logline(string $msg): void
{
    if (!is_dir(DATA_DIR)) {
        @mkdir(DATA_DIR, 0770, true);
    }
    // гарантия валидного UTF-8: битые байты (обрезка payload'ов и т.п.)
    // заменяются, чтобы журнал читался целиком
    $msg = mb_scrub($msg, 'UTF-8');
    @file_put_contents(LOG_PATH, gmdate('Y-m-d H:i:s') . " | " . $msg . "\n", FILE_APPEND);
}

/** Чтение/запись реестра под flock (события могут прийти пачкой). */
function reg_load(): array
{
    if (!is_file(REG_PATH)) {
        return ["users" => []];
    }
    $fh = fopen(REG_PATH, 'r');
    if (!$fh) {
        logline("FATAL reg_load open fail");
        return ["users" => []];
    }
    flock($fh, LOCK_SH);
    $raw = stream_get_contents($fh);
    flock($fh, LOCK_UN);
    fclose($fh);
    $reg = json_decode((string)$raw, true);
    return is_array($reg) && isset($reg['users']) && is_array($reg['users'])
        ? $reg : ["users" => []];
}

function reg_save(array $reg): void
{
    if (!is_dir(DATA_DIR)) {
        @mkdir(DATA_DIR, 0770, true);
    }
    $fh = fopen(REG_PATH, 'c');
    if (!$fh) {
        logline("FATAL reg_save open fail");
        return;
    }
    flock($fh, LOCK_EX);
    ftruncate($fh, 0);
    fwrite($fh, json_encode($reg, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . "\n");
    fflush($fh);
    flock($fh, LOCK_UN);
    fclose($fh);
}

function churn_append(array $rec): void
{
    if (!is_dir(DATA_DIR)) {
        @mkdir(DATA_DIR, 0770, true);
    }
    $fh = fopen(CHURN_PATH, 'a');
    if (!$fh) {
        return;
    }
    flock($fh, LOCK_EX);
    fwrite($fh, json_encode($rec, JSON_UNESCAPED_UNICODE) . "\n");
    fflush($fh);
    flock($fh, LOCK_UN);
    fclose($fh);
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
        CURLOPT_TIMEOUT        => 60,
    ]);
    // API MAX использует цепочку Минцифры: подкладываем свой бандл.
    if (is_file(CA_FILE)) {
        curl_setopt($ch, CURLOPT_CAINFO, CA_FILE);
        curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
    }
    $body   = curl_exec($ch);
    $code   = (int)curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $errno  = curl_errno($ch);
    $errstr = curl_error($ch);
    curl_close($ch);
    $json = is_string($body) ? json_decode($body, true) : [];
    if ($code !== 200) {
        logline("API FAIL $method $path -> code=$code curl($errno): $errstr "
            . mb_substr((string)$body, 0, 200));
    }
    return ['code' => $code, 'body' => is_array($json) ? $json : []];
}

function send_dialog(int $chatId, string $text): bool
{
    $r = api('POST', '/messages?chat_id=' . $chatId . '&notify=true', [
        'text'   => $text,
        'format' => 'markdown',
    ]);
    usleep(600000); // лимит 2 сообщения/сек на чат
    return $r['code'] === 200;
}

// ---------- нормализация и разбор брифа (порт brief.py) -------------------

/** NBSP и похожие пробелы -> обычный; неровный дефис -> обычный. */
function norm(string $s): string
{
    $s = str_replace(["\u{00A0}", "\u{202F}", "\u{2011}", "\u{2013}", "\u{2014}"],
                     [" ", " ", "-", "-", "-"], $s);
    return $s;
}

function value_after_label(array $lines, string $label): ?string
{
    // Метка может стоять не в начале строки, но не внутри слова.
    $pattern = '/(?:^|[^\p{L}\p{N}_])' . $label . '\s*[:\-—–]\s*(.+?)\s*$/iu';
    foreach ($lines as $line) {
        if (preg_match($pattern, norm($line), $m)) {
            return $m[1];
        }
    }
    return null;
}

function split_list(string $value): array
{
    $parts = preg_split('/[,;\/]/u', $value) ?: [];
    $out = [];
    foreach ($parts as $p) {
        $p = trim($p, " .\u{2013}-");
        if ($p !== '') {
            $out[] = $p;
        }
    }
    return $out;
}

function is_stop(string $text): bool
{
    $t = trim(mb_strtolower(trim(norm($text))));
    if ($t === '' ) {
        return false;
    }
    $first = mb_split('\s', $t)[0];
    $stop = ['стоп', 'стоп.', 'стоп!', 'стоп,', 'хватит', 'отписка'];
    return in_array($t, $stop, true) || ($first === 'стоп' && $t === 'стоп');
}

/**
 * Порт parse_brief: ok=true => themes/frequency/sources/warnings,
 * ok=false => reason (человекочитаемо).
 */
function parse_brief(string $text): array
{
    $warnings = [];
    $lines = explode("\n", norm($text));

    $themesRaw = value_after_label($lines, 'темы');
    $themes = $themesRaw !== null ? split_list($themesRaw) : [];
    if (!$themes) {
        return ["ok" => false,
            "reason" => "В сообщении нет строки «темы: …» — напишите темы через запятую."];
    }
    if (count($themes) > 5) {
        $themes = array_slice($themes, 0, 5);
        $warnings[] = "Тем больше 5 — оставил первые 5, остальные проигнорировал.";
    }

    $freqRaw = value_after_label($lines, 'частота');
    $frequency = ["kind" => "daily"];
    if ($freqRaw !== null) {
        $f = mb_strtolower(norm($freqRaw));
        $aliases = [
            'раз в день'       => ["kind" => "daily"],
            'в день раз'       => ["kind" => "daily"],
            'утром и вечером'  => ["kind" => "twice"],
            'утром+вечером'    => ["kind" => "twice"],
            'утром + вечером'  => ["kind" => "twice"],
            'дважды в день'    => ["kind" => "twice"],
            'по вечерам'       => ["kind" => "daily", "hour_hint" => "evening"],
            'по утрам'         => ["kind" => "daily", "hour_hint" => "morning"],
            'только будни'     => ["kind" => "daily", "weekdays_only" => true],
            'будни'            => ["kind" => "daily", "weekdays_only" => true],
            'ежедневно'        => ["kind" => "daily"],
        ];
        foreach ($aliases as $alias => $mapped) {
            if (mb_strpos($f, $alias) === 0 || mb_strpos($f, $alias) !== false) {
                $frequency = $mapped;
                break;
            }
        }
        if ($frequency === ["kind" => "daily"]) {
            $variants = array_map('mb_strtolower', split_list($freqRaw));
            if (in_array('утром', $variants, true)
                && (in_array('вечером', $variants, true) || in_array('вечер', $variants, true))) {
                $frequency = ["kind" => "twice"];
            } elseif (in_array('будни', $variants, true)) {
                $frequency = ["kind" => "daily", "weekdays_only" => true];
            } elseif (in_array('вечером', $variants, true)) {
                $frequency = ["kind" => "daily", "hour_hint" => "evening"];
            } elseif (in_array('утром', $variants, true)) {
                $frequency = ["kind" => "daily", "hour_hint" => "morning"];
            } else {
                $warnings[] = "«частота: $freqRaw» не распознана — поставил «раз в день». "
                    . "Варианты: раз в день / утром+вечером / только будни.";
            }
        }
    }

    $sourcesRaw = value_after_label($lines, 'источники');
    $sources = $sourcesRaw !== null ? split_list($sourcesRaw) : [];

    return ["ok" => true, "themes" => $themes, "frequency" => $frequency,
            "sources" => $sources, "warnings" => $warnings];
}

function frequency_text(array $freq): string
{
    $labels = [
        "daily" => "раз в день",
        "twice" => "дважды в день (утром и вечером)",
    ];
    $parts = [$labels[$freq['kind']] ?? "раз в день"];
    if (!empty($freq['weekdays_only'])) {
        $parts[] = "только будни";
    }
    if (($freq['hour_hint'] ?? '') === 'evening') {
        $parts[] = "вечером";
    }
    if (($freq['hour_hint'] ?? '') === 'morning') {
        $parts[] = "утром";
    }
    return implode(" — ", $parts);
}

function receipt_text(array $user, array $warnings): string
{
    $themes = $user['themes'] ?? [];
    $body = "**Настройка принята**\n"
        . "• Темы: " . implode(', ', $themes) . "\n"
        . "• Частота: " . frequency_text($user['frequency'] ?? []) . "\n";
    $sources = $user['sources'] ?? [];
    $body .= $sources
        ? "• Источники: " . implode(', ', $sources)
        : "• Источники: не заданы";
    if ($warnings) {
        $body .= "\n\n" . implode("\n", array_map(fn($w) => "· " . $w, $warnings));
    }
    $body .= "\n\nПеренастроить: напишите новое сообщение «темы: …». "
        . "Остановить: напишите «стоп».";
    return $body;
}

// ---------- обработка (порт digest_bot.py) --------------------------------

function remember_mid(array &$user, string $mid): void
{
    if ($mid === '') {
        return;
    }
    $seen = $user['seen_mids'] ?? [];
    if (!in_array($mid, $seen, true)) {
        $seen[] = $mid;
    }
    if (count($seen) > 200) {
        $seen = array_slice($seen, -200);
    }
    $user['seen_mids'] = $seen;
}

function churn_ts($tsMs): string
{
    if (!$tsMs) {
        return "";
    }
    $dt = (new DateTimeImmutable('@' . intdiv((int)$tsMs, 1000)))
        ->setTimezone(new DateTimeZone('+03:00'));
    return $dt->format(DATE_ATOM);
}

function record_churn(array $upd): void
{
    $type = $upd['update_type'] ?? '';
    if ($type !== 'user_added' && $type !== 'user_removed') {
        return;
    }
    $chatId = $upd['chat_id'] ?? null;
    if (!is_int($chatId) || $chatId >= 0) {
        return; // интересуют только каналы/группы
    }
    $u = $upd['user'] ?? [];
    churn_append([
        "ts"      => churn_ts($upd['timestamp'] ?? 0),
        "event"   => $type,
        "chat_id" => $chatId,
        "user_id" => $u['user_id'] ?? null,
        "name"    => trim((string)($u['name'] ?? '')),
    ]);
}

function owner_reply(array $reg, string $text): array
{
    // «отв <user_id> текст» — ручной ответ владельца; возвращает reg обратно.
    if (!preg_match('/^\s*(?:отв|ответ)\s+(\d+)\s*[:\-—]?\s*(.+)$/su', $text, $m)) {
        send_dialog((int)OWNER_CHAT_ID,
            "Формат ответа: «отв <id> <текст>» — id есть в пересланных "
            . "обращениях. Например: отв 326451299 Здравствуйте!");
        logline("owner_reply_fail bad format");
        return $reg;
    }
    $target = $reg['users'][$m[1]] ?? null;
    if (!$target || empty($target['dialog_chat_id'])) {
        send_dialog((int)OWNER_CHAT_ID,
            "Нет диалога с пользователем {$m[1]} в реестре — "
            . "он не стартовал бота или диалог не зафиксирован.");
        logline("owner_reply_fail no dialog {$m[1]}");
        return $reg;
    }
    $ok = send_dialog((int)$target['dialog_chat_id'], trim($m[2]));
    logline("owner_reply -> {$m[1]} status=" . ($ok ? '200' : 'FAIL'));
    return $reg;
}

function forward_inquiry(array &$user, string $userId, string $text): void
{
    send_dialog((int)$user['dialog_chat_id'], ACK_TEXT);
    $stamp = (new DateTimeImmutable('now', new DateTimeZone('+03:00')))->format('H:i');
    $name = $user['owner_name'] ?? 'без имени';
    $fwd = "**Обращение** от $name (id $userId, $stamp):\n\n"
        . mb_substr($text, 0, 2000);
    send_dialog(OWNER_CHAT_ID, $fwd);
    logline("inquiry owner=$userId len=" . mb_strlen($text));
}

function process_message(array $reg, string $mid, array $sender, string $text): array
{
    $senderId = (string)($sender['user_id'] ?? '');
    if ($senderId === '' || !empty($sender['is_bot'])) {
        return $reg; // Ч5: свои сообщения бота не парсим
    }

    if ($senderId === OWNER_USER_ID) {
        // сообщения владельца в его диалоге = ручные ответы адресатам
        return owner_reply($reg, $text);
    }

    $user = $reg['users'][$senderId] ?? [
        "owner_user_id" => (int)$senderId,
        "owner_name"    => trim((($sender['first_name'] ?? '') . ' '
                                . ($sender['last_name'] ?? ''))),
    ];
    remember_mid($user, $mid);

    if (is_stop($text)) {
        $user['state'] = "stopped";
        $reg['users'][$senderId] = $user;
        reg_save($reg);
        logline("stop owner=$senderId");
        return $reg;
    }

    $isBriefAttempt = mb_stripos($text, 'темы:') !== false;
    $parsed = $isBriefAttempt ? parse_brief($text) : ["ok" => false, "reason" => ""];

    if ($isBriefAttempt && !$parsed['ok']) {
        $reply = "Не распознал настройку.\n\n" . $parsed['reason'] . "\n\n" . FORM_HINT;
        if (!empty($user['dialog_chat_id'])) {
            send_dialog((int)$user['dialog_chat_id'], $reply);
        }
        $reg['users'][$senderId] = $user;
        reg_save($reg);
        logline("brief_fail owner=$senderId");
        return $reg;
    }

    if (!$parsed['ok']) {
        // обычное обращение: квитанция + копия владельцу
        $reg['users'][$senderId] = $user;
        reg_save($reg);
        forward_inquiry($user, $senderId, $text);
        return $reg;
    }

    $user['state']          = "active";
    $user['themes']         = $parsed['themes'];
    $user['frequency']      = $parsed['frequency'];
    $user['sources']        = $parsed['sources'];
    $user['brief_text']     = mb_substr($text, -2000);
    $user['configured_at']  = (new DateTimeImmutable('now', new DateTimeZone('+03:00')))
        ->format(DATE_ATOM);
    $reg['users'][$senderId] = $user;
    reg_save($reg);
    logline("brief_ok owner=$senderId themes=" . implode(',', $parsed['themes']));
    if (!empty($user['dialog_chat_id'])) {
        send_dialog((int)$user['dialog_chat_id'], receipt_text($user, $parsed['warnings']));
    }
    return $reg;
}

function process_bot_started(array $reg, array $upd): array
{
    $chatId = $upd['chat_id'] ?? 0;
    $u      = $upd['user'] ?? [];
    $userId = (string)($u['user_id'] ?? '');
    if ($userId === '' || !is_int($chatId) || $chatId <= 0) {
        return $reg;
    }
    $user = $reg['users'][$userId] ?? [
        "owner_user_id" => (int)$userId,
        "owner_name"    => trim((string)($u['name'] ?? '')),
    ];
    if (empty($user['dialog_chat_id'])) {
        $user['dialog_chat_id'] = $chatId;
    }
    if (empty($user['owner_name'])) {
        $user['owner_name'] = trim((string)($u['name'] ?? ''));
    }
    if (($user['state'] ?? '') === 'stopped') {
        $user['state'] = "new"; // вернулся — снова ждём бриф
    }
    $reg['users'][$userId] = $user;
    reg_save($reg);
    logline("bot_started owner=$userId chat=$chatId");
    send_dialog($chatId, GREETING_TEXT);
    return $reg;
}

// ---------- точка входа ---------------------------------------------------

// 1) секрет: заголовок X-Max-Bot-Api-Secret (основной) или ?s= (резерв)
$given = (string)($_SERVER['HTTP_X_MAX_BOT_API_SECRET'] ?? '');
if ($given === '') {
    $given = (string)($_GET['s'] ?? '');
}
if (!hash_equals(SECRET, $given)) {
    http_response_code(403);
    exit('forbidden');
}

// 2) событие
$raw = file_get_contents('php://input');
$upd = json_decode((string)$raw, true);
if (!is_array($upd)) {
    http_response_code(400);
    exit('bad payload');
}

// 3) 200 сразу, обработка — после разрыва соединения
http_response_code(200);
header('Content-Type: text/plain');
echo 'ok';
if (function_exists('fastcgi_finish_request')) {
    fastcgi_finish_request();
}

if (!is_dir(DATA_DIR)) {
    @mkdir(DATA_DIR, 0770, true);
}

$type = (string)($upd['update_type'] ?? '');
logline("EVENT $type");

$reg = reg_load();

switch ($type) {
    case 'user_added':
    case 'user_removed':
        record_churn($upd);
        break;

    case 'bot_started':
        $reg = process_bot_started($reg, $upd);
        break;

    case 'message_created':
    case 'message_edited':
        $m = $upd['message'] ?? [];
        $r = $m['recipient'] ?? [];
        if (($r['chat_type'] ?? '') === 'dialog') {
            $mid    = (string)(($m['body'] ?? [])['mid'] ?? '');
            $sender = $m['sender'] ?? [];
            $text   = (string)(($m['body'] ?? [])['text'] ?? '');
            // дедуп: событие могло уже быть обработано
            $uid = (string)($sender['user_id'] ?? '');
            $seen = ($reg['users'][$uid]['seen_mids'] ?? []);
            if ($uid !== '' && in_array($mid, $seen, true)) {
                break;
            }
            if ($uid !== OWNER_USER_ID) {
                // первый контакт: создаём запись до парсинга
                if (!isset($reg['users'][$uid])) {
                    $reg['users'][$uid] = [
                        "owner_user_id" => (int)$uid,
                        "owner_name"    => trim((($sender['first_name'] ?? '') . ' '
                                                . ($sender['last_name'] ?? ''))),
                        "dialog_chat_id" => $r['chat_id'] ?? null,
                    ];
                } elseif (empty($reg['users'][$uid]['dialog_chat_id'])) {
                    $reg['users'][$uid]['dialog_chat_id'] = $r['chat_id'] ?? null;
                }
            }
            $reg = process_message($reg, $mid, $sender, $text);
        }
        break;

    case 'bot_stopped':
    case 'dialog_removed':
    case 'dialog_cleared':
    case 'dialog_muted':
        // реестр не трогаем (паритет с digest_bot.py poll)
        break;

    default:
        logline("UNHANDLED $type: " . mb_substr((string)$raw, 0, 300));
}
