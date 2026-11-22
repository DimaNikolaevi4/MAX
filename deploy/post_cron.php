<?php
/**
 * post_cron.php — автопилот публикаций постов блогера (каналы MAX).
 *
 * Источник: публичный репо MAX на GitHub (raw.githubusercontent.com).
 * Состояние: /0s3/blogger-data/state/<канал>_state.json (flock).
 * Обложки:   /0s3/public_html/blogger/covers/<канал>/<YYYY-MM-DD>-cover.png (FTP, открытые URL).
 * Токены:    /0s3/blogger-data/<канал>_token.txt (вне webroot).
 * Лог:       stdout (cron >> post_cron.log).
 *
 * Режимы:
 *   CLI (cron): php post_cron.php            — крон запускает в минуты публикаций
 *              (crontab: 07:15–07:45 — утренний прогон и статистика; 12:00 — Format 1;
 *              19:30 — zabava; 20:00 — catden; 21:30 — посты плана ainow);
 *              gate: gate_time (ранний слот) и publish_time поста/канала
 *   web (обёртка post_web.php, секрет):      ?s=<секрет>       — DRY: сводка без отправок
 *                                            ?s=<секрет>&go=1  — реальный запуск вне расписания
 * GHOST: если в state ghost=true — НЕ отправляет, только логирует
 *        (период параллельной проверки; снять флаг — крон работает по-настоящему).
 * В DRY/ghost дополнительно проверяется завтрашний день (конвейер-проверка).
 *
 * Требования: PHP 8.1+, curl. Не трогать чужие каталоги хостинга.
 */

declare(strict_types=1);

date_default_timezone_set('Europe/Moscow');

const REPO = 'DimaNikolaevi4/MAX';
const BRANCH = 'main';
const API_BASE = 'https://platform-api2.max.ru';
const TEXT_LIMIT = 4000;

// Хостинг-каталоги (абсолютные).
$DATA_DIR = '/home/m/mitiba/0s3/blogger-data';

/**
 * Каналы: включены = enabled=true. Новые добавлять здесь же.
 * Обложки: covers/<dir>/<date>-cover.png (или -cover-1.png, -cover-2.png … карусель).
 */
$CHANNELS = [
    'ainow' => [
        'enabled' => true,
        'token_file' => $DATA_DIR . '/ainow_token.txt',
        'chat_id' => -76964086179165,
        'posts_path' => 'roles/blogger/channels/ainow/posts',
        'cover_dir' => '/home/m/mitiba/0s3/public_html/blogger/covers/ainow',
        'cover_url' => 'https://0s3.ru/blogger/covers/ainow',
        'state_file' => $DATA_DIR . '/state/ainow_state.json',
        'publish_time' => '21:30', // МСК: слот постов плана (по умолчанию для постов без publish_time)
        'gate_time' => '12:00',    // МСК: ранний слот — кросс-пост Format 1 (publish_time в посте)
    ],
    'catden' => [
        'enabled' => true,
        'token_file' => $DATA_DIR . '/catden_token.txt',
        'chat_id' => -81170615067997,
        'posts_path' => 'roles/blogger/channels/catden/posts',
        'cover_dir' => '/home/m/mitiba/0s3/public_html/blogger/covers/catden',
        'cover_url' => 'https://0s3.ru/blogger/covers/catden',
        'media_dir' => $DATA_DIR . '/media/catden', // /media/catden/<дата>/<файл> (FTP)
        'state_file' => $DATA_DIR . '/state/catden_state.json',
        'publish_time' => '20:00', // 18.11.2026: перенос на 20:00 МСК (решение владельца)
    ],
    'zabava' => [
        'enabled' => true,
        'token_file' => $DATA_DIR . '/zabava_token.txt',
        'chat_id' => -71021572420957,
        'posts_path' => 'roles/blogger/channels/zabava/posts',
        'cover_dir' => '/home/m/mitiba/0s3/public_html/blogger/covers/zabava',
        'cover_url' => 'https://0s3.ru/blogger/covers/zabava',
        'media_dir' => $DATA_DIR . '/media/zabava', // видео/фото из архива (FTP)
        'state_file' => $DATA_DIR . '/state/zabava_state.json',
        'publish_time' => '19:30', // 18.11.2026: ?????????? ? 07:16 (??????? ?????????)
    ],
];

$IS_WEB = isset($_SERVER['REQUEST_METHOD']);
$isDry = false;

if ($IS_WEB) {
    $secretFile = $DATA_DIR . '/blogger_secret.txt';
    $secret = is_file($secretFile) ? trim((string) file_get_contents($secretFile)) : '';
    $given = (string) ($_GET['s'] ?? '');
    if ($secret === '' || !hash_equals($secret, $given)) {
        http_response_code(403);
        header('Content-Type: text/plain; charset=utf-8');
        echo 'forbidden';
        exit;
    }
    $isDry = !isset($_GET['go']);
} else {
    $isDry = in_array('--dry', $argv, true);
}

header('Content-Type: text/plain; charset=utf-8');
logLine(sprintf('=== запуск %s (%s) PHP %s', date('c'), $isDry ? 'DRY' : 'REAL', PHP_VERSION));

foreach ($CHANNELS as $slug => $conf) {
    if (!$conf['enabled']) {
        continue;
    }
    if (!$IS_WEB && !$isDry) {
        // Время публикации канала (крон уже запускает в точные минуты;
        // gate здесь — страховка: до gate_time ничего не публикуем).
        // gate_time — самый ранний слот канала (например, кросс-пост Format 1
        // в 12:00), publish_time — слот по умолчанию для постов плана.
        if (date('H:i') < ($conf['gate_time'] ?? $conf['publish_time'] ?? '21:30')) {
            continue;
        }
    }
    runChannel($slug, $conf, $isDry, $DATA_DIR);
}

logLine('=== конец запуска каналов');

// Статистика каналов (снапшоты) — после всех публикаций, в 07:45-запуске.
if (!$isDry && date('H:i') >= '07:45' && date('H:i') < '09:00') {
    logLine('=== статистика каналов');
    require_once __DIR__ . '/stats_cron.php';
    statsRunAll($DATA_DIR, $isDry);
}
exit;

/* ------------------------------------------------------------------ */

function runChannel(string $slug, array $conf, bool $isDry, string $dataDir): void
{
    $state = loadState($conf['state_file']);
    $ghost = (bool) ($state['ghost'] ?? false);
    $tag = "[$slug]";

    // 1. Список постов канала из GitHub API.
    $apiUrl = sprintf('https://api.github.com/repos/%s/contents/%s?ref=%s', REPO, $conf['posts_path'], BRANCH);
    $files = httpGetJson($apiUrl);
    if (!is_array($files)) {
        logLine("$tag FAIL GitHub API: " . (is_string($files) ? $files : 'неизвестная ошибка'));
        return;
    }

    // Рабочий день: сегодня; в DRY/ghost — также завтра (проверка конвейера).
    $today = date('Y-m-d');
    $days = [$today];
    if ($isDry || $ghost) {
        $days[] = date('Y-m-d', strtotime('+1 day'));
    }

    foreach ($days as $day) {
        $candidates = [];
        foreach ($files as $f) {
            if (($f['type'] ?? '') !== 'file' || !str_ends_with($f['name'] ?? '', '.md')) {
                continue;
            }
            if (str_starts_with($f['name'], $day . '-')) {
                $candidates[] = $f['name'];
            }
        }
        logLine(sprintf('%s кандидатов на %s: %d', $tag, $day, count($candidates)));

        foreach ($candidates as $name) {
            if (isset($state['published'][$name])) {
                continue; // уже опубликовано
            }
            $raw = httpGet(sprintf('https://raw.githubusercontent.com/%s/%s/%s/%s', REPO, BRANCH, $conf['posts_path'], $name));
            if ($raw === null || $raw === '') {
                logLine("$tag FAIL raw: $name");
                continue;
            }
            [$meta, $text] = parsePost($raw);
            $status = $meta['status'] ?? 'draft';
            if ($status !== 'approved') {
                logLine("$tag skip $name: status=$status");
                continue;
            }
            if (mb_strlen($text) > TEXT_LIMIT) {
                logLine(sprintf('%s FAIL %s: текст %d > %d', $tag, $name, mb_strlen($text), TEXT_LIMIT));
                continue;
            }

            // Слот конкретного поста: publish_time во front matter (например,
            // кросс-пост Format 1 — 12:00); иначе — слот канала (посты плана).
            if (!$isDry && !$ghost) {
                $postTime = (string) ($meta['publish_time'] ?? ($conf['publish_time'] ?? ''));
                if ($postTime !== '' && date('H:i') < $postTime) {
                    logLine("$tag wait $name: publish_time=$postTime");
                    continue;
                }
            }

            // Гейт запрещённых организаций (правило владельца 12.11.2026,
            // docs/forbidden-orgs.md) — на ЛЮБОМ посте, fail-closed: без
            // forbidden_orgs.json на FTP ничего не публикуем.
            $fob = loadForbiddenPatterns($dataDir);
            if ($fob === null) {
                logLine("$tag FAIL $name: нет forbidden_orgs.json — гейт запрещённых организаций не может отработать");
                continue;
            }
            $hit = forbiddenHit($text, $fob);
            if ($hit !== null) {
                logLine(sprintf('%s FAIL %s: запрещённая организация: %s — весь связанный контекст удаляется, новость заменяется (docs/forbidden-orgs.md)', $tag, $name, $hit));
                continue;
            }

            // 2. Медиа поста: либо image_file/image_files из FTP
            //    ($DATA_DIR/media/<канал>/<дата>/<файл> — медиа catden не в git),
            //    либо обложка(и) covers/<канал>/<дата>-cover*.png (ainow).
            $media = [];
            $fmlist = [];
            if (!empty($meta['video_file'])) {
                $fmlist[] = (string) $meta['video_file'];
            }
            if (!empty($meta['image_file'])) {
                $fmlist[] = (string) $meta['image_file'];
            }
            if (!empty($meta['image_files'])) {
                foreach (explode('|', (string) $meta['image_files']) as $x) {
                    $x = trim($x);
                    if ($x !== '') {
                        $fmlist[] = $x;
                    }
                }
            }
            if ($fmlist) {
                // image_file/image_files: у catden — медиа из FTP
                // ($DATA_DIR/media/<канал>/<дата>/<файл>, в git их нет);
                // у ainow image_file = имя обложки из covers/<канал>/.
                $baseDir = !empty($conf['media_dir'])
                    ? rtrim((string) $conf['media_dir'], '/') . '/' . $day
                    : rtrim((string) $conf['cover_dir'], '/');
                $missing = [];
                foreach ($fmlist as $rel) {
                    $p = $baseDir . '/' . basename($rel);
                    if (is_file($p)) {
                        $media[] = $p;
                    } else {
                        $missing[] = basename($rel);
                    }
                }
                if ($missing) {
                    logLine(sprintf('%s FAIL %s: медиа не найдено на FTP (%s)', $tag, $name, implode(', ', $missing)));
                    continue;
                }
            } else {
                $media = findCovers($conf['cover_dir'], $day, $meta);
                if (!$media) {
                    logLine("$tag FAIL $name: обложка не найдена (covers/{$day}-cover*.png)");
                    continue;
                }
            }
            $describe = sprintf('%s, медиа: %d (%s)', $name, count($media),
                implode(',', array_map('basename', $media)));
            if ($isDry || $ghost) {
                logLine(sprintf('%s %s: %s', $tag, $ghost ? '[ghost] WOULD' : '[dry] WOULD', $describe));
                continue;
            }

            // 3. Реальная публикация — только для сегодняшнего дня.
            if ($day !== $today) {
                logLine("$tag skip $name: дата $day не сегодня");
                continue;
            }
            $result = publishPost($conf, $text, $media, $meta);
            if ($result['ok']) {
                $state['published'][$name] = [
                    'mid' => $result['mid'],
                    'at' => date('c'),
                    'media' => array_map('basename', $media),
                ];
                saveState($conf['state_file'], $state);
                logLine("$tag OK $name mid={$result['mid']}");
                // Медиа больше не нужны (картинки ушли в MAX, CDN) — удаляем.
                foreach ($media as $c) {
                    if (@unlink($c)) {
                        logLine("$tag media deleted: " . basename($c));
                    } else {
                        logLine("$tag WARN unlink fail: " . basename($c));
                    }
                }
            } else {
                logLine("$tag FAIL $name: {$result['error']}");
            }
        }
    }
}

/** Паттерны запрещённых организаций (fail-closed): null = нет файла. */
function loadForbiddenPatterns(string $dataDir): ?array
{
    $path = $dataDir . '/forbidden_orgs.json';
    if (!is_file($path)) {
        return null;
    }
    $raw = file_get_contents($path);
    $cfg = json_decode((string) $raw, true);
    if (!is_array($cfg)) {
        return null;
    }
    $out = [];
    foreach (($cfg['patterns'] ?? []) as $p) {
        $pat = is_array($p) ? (string) ($p['pattern'] ?? '') : (string) $p;
        $pat = trim($pat);
        if ($pat === '') {
            continue;
        }
        // префикс "re:" — сырой regex (склонения); иначе слово целиком.
        // /iu — UTF-8 (кириллица) без учёта регистра, как в shared/forbidden_orgs.py.
        $out[$pat] = $pat !== 're' && str_starts_with($pat, 're:')
            ? '/' . substr($pat, 3) . '/iu'
            : '/\b' . preg_quote($pat, '/') . '\b/iu';
    }
    return $out ?: null;
}

/** Текст упоминает запрещённую организацию? Возвращает паттерн или null. */
function forbiddenHit(string $text, array $patterns): ?string
{
    foreach ($patterns as $pat => $rx) {
        if (@preg_match($rx, $text) === 1) {
            return $pat;
        }
    }
    return null;
}

/** Разбор front matter. */
function parsePost(string $raw): array
{
    $raw = str_replace("\xEF\xBB\xBF", '', $raw);
    if (preg_match('/^---\r?\n(.*?)\r?\n---\r?\n?(.*)$/s', $raw, $m)) {
        $meta = [];
        foreach (preg_split('/\r?\n/', $m[1]) as $line) {
            if (str_contains($line, ':')) {
                [$k, $v] = array_map('trim', explode(':', $line, 2));
                $meta[$k] = $v;
            }
        }
        return [$meta, trim($m[2])];
    }
    return [[], trim($raw)];
}

/** Обложки: <date>-cover.png или <date>-cover-N.png (карусель). */
function findCovers(string $dir, string $date, array $meta): array
{
    $covers = [];
    if (!is_dir($dir)) {
        return $covers;
    }
    $single = $dir . '/' . $date . '-cover.png';
    if (is_file($single)) {
        $covers[] = $single;
        return $covers;
    }
    for ($i = 1; $i <= 10; $i++) {
        $p = $dir . '/' . $date . '-cover-' . $i . '.png';
        if (is_file($p)) {
            $covers[] = $p;
        }
    }
    return $covers;
}

/** Публикация: upload медиа (фото/видео) + POST /messages. */
function publishPost(array $conf, string $text, array $media, array $meta): array
{
    $token = trim((string) file_get_contents($conf['token_file']));
    if ($token === '') {
        return ['ok' => false, 'error' => 'пустой токен'];
    }
    $attachments = [];
    foreach ($media as $path) {
        $up = uploadMedia($token, $path);
        if (!$up) {
            return ['ok' => false, 'error' => 'upload fail: ' . basename($path)];
        }
        $attachments[] = ['type' => $up['kind'], 'payload' => ['token' => $up['token']]];
    }
    $payload = ['text' => $text, 'format' => ($meta['format'] ?? 'markdown')];
    if ($attachments) {
        $payload['attachments'] = $attachments;
    }
    // MAX обрабатывает медиа асинхронно: при attachment.not.ready — повтор
    // (паузы 3/6/10/15 с, как READY_DELAYS в publish_video.py).
    $delays = [3, 6, 10, 15];
    for ($try = 0; ; $try++) {
        [$code, $body] = httpPostJson(
            API_BASE . '/messages?chat_id=' . (int) $conf['chat_id'],
            $token,
            $payload
        );
        $data = json_decode((string) $body, true);
        if ($code === 200 && isset($data['message']['body']['mid'])) {
            return ['ok' => true, 'mid' => $data['message']['body']['mid']];
        }
        $errText = (string) $body;
        if ($try < count($delays) && str_contains($errText, 'attachment.not.ready')) {
            logLine('attachment.not.ready, повтор через ' . $delays[$try] . ' с');
            sleep($delays[$try]);
            continue;
        }
        return ['ok' => false, 'error' => "HTTP $code: " . substr($errText, 0, 200)];
    }
}

/** Загрузка медиа (фото или видео): POST /uploads -> POST файла -> token. */
function uploadMedia(string $token, string $path): ?array
{
    $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
    $video = in_array($ext, ['mp4', 'mov', 'mkv', 'webm'], true);
    $kind = $video ? 'video' : 'image';
    $mime = ['mp4' => 'video/mp4', 'mov' => 'video/quicktime',
             'mkv' => 'video/x-matroska', 'webm' => 'video/webm',
             'jpg' => 'image/jpeg', 'jpeg' => 'image/jpeg',
             'png' => 'image/png', 'webp' => 'image/webp',
             'gif' => 'image/gif'][$ext] ?? 'application/octet-stream';
    [$code, $body] = httpPostJson(API_BASE . '/uploads?type=' . $kind, $token, []);
    $head = json_decode((string) $body, true);
    $url = $head['url'] ?? null;
    if ($code !== 200 || !$url) {
        logLine('upload head fail: ' . substr((string) $body, 0, 150));
        return null;
    }
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 300,
        CURLOPT_HTTPHEADER => ['Authorization: ' . $token],
        CURLOPT_POSTFIELDS => ['data' => new CURLFile($path, $mime, basename($path))],
        CURLOPT_CAINFO => CA_INFO(),
    ]);
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($resp === false || $code >= 400) {
        logLine('upload file fail: HTTP ' . $code . ' ' . $err);
        return null;
    }
    $done = json_decode((string) $resp, true);
    $tokenUp = $done['photos']['0']['token'] ?? $done['videos']['0']['token'] ?? $head['token'] ?? null;
    return $tokenUp ? ['kind' => $kind, 'token' => $tokenUp] : null;
}

/** Загрузка состояния (flock, чтение). */
function loadState(string $path): array
{
    if (!is_file($path)) {
        return [];
    }
    $fp = fopen($path, 'r');
    if (!$fp) {
        return [];
    }
    flock($fp, LOCK_SH);
    $raw = stream_get_contents($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
    $state = json_decode((string) $raw, true);
    return is_array($state) ? $state : [];
}

/** Сохранение состояния (flock, LOCK_EX). */
function saveState(string $path, array $state): void
{
    $fp = fopen($path, 'c');
    if (!$fp) {
        logLine('FAIL state write: ' . $path);
        return;
    }
    flock($fp, LOCK_EX);
    ftruncate($fp, 0);
    fwrite($fp, json_encode($state, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));
    fflush($fp);
    flock($fp, LOCK_UN);
    fclose($fp);
}

/** GET (текст): TLS системный CA, фолбэк на минцифры-бандл. */
function httpGet(string $url): ?string
{
    foreach (['SYS', 'MINC'] as $ca) {
        $ch = curl_init($url);
        $opts = [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 15,
            CURLOPT_TIMEOUT => 60,
            CURLOPT_USERAGENT => 'MAX-blogger-cron/1.0',
        ];
        if ($ca === 'MINC') {
            $opts[CURLOPT_CAINFO] = CA_INFO();
        }
        curl_setopt_array($ch, $opts);
        $resp = curl_exec($ch);
        $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        $err = curl_error($ch);
        curl_close($ch);
        if ($resp !== false && $code === 200) {
            return (string) $resp;
        }
        logLine("GET retry($ca): HTTP $code $err");
    }
    return null;
}

/** GET JSON (GitHub API). */
function httpGetJson(string $url)
{
    $raw = httpGet($url);
    if ($raw === null) {
        return 'GitHub недоступен';
    }
    $data = json_decode($raw, true);
    if (isset($data['message'])) {
        return 'GitHub API: ' . $data['message'];
    }
    return $data;
}

/** POST JSON в MAX API. Возвращает [код, тело]. */
function httpPostJson(string $url, string $token, array $payload): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 15,
        CURLOPT_TIMEOUT => 90,
        CURLOPT_HTTPHEADER => [
            'Authorization: ' . $token,
            'Content-Type: application/json',
        ],
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_CAINFO => CA_INFO(),
    ]);
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($resp === false) {
        return [0, 'curl: ' . $err];
    }
    return [$code, (string) $resp];
}

function CA_INFO(): string
{
    return '/home/m/mitiba/0s3/blogger-data/russian_ca_bundle.pem';
}

function logLine(string $msg): void
{
    $line = '[' . date('H:i:s') . '] ' . $msg;
    echo $line . "\n";
}
