<?php
/**
 * post.php — публикация поста в канал мессенджера MAX через Bot API.
 *
 * Использование:
 *   php bin/post.php <путь-к-посту.md>            — опубликовать пост
 *   php bin/post.php <путь-к-посту.md> --dry-run  — показать payload, не отправляя
 *
 * Опции:
 *   --dry-run       Не отправлять, только показать, что будет отправлено.
 *   --chat-id=N     Временно переопределить chat_id (для отладки).
 *
 * Переменные окружения:
 *   MAX_TOKENS_FILE — путь к файлу токенов (по умолчанию local/tokens.json);
 *   MAX_API_BASE    — адрес API (по умолчанию https://platform-api2.max.ru);
 *   MAX_CA_CERT     — путь к CA-сертификату (например, сертификат Минцифры);
 *   MAX_INSECURE=1  — отключить проверку TLS (только для отладки).
 *
 * Требования: PHP 8.1+, расширение curl. См. AGENTS.md — жизненный цикл поста.
 */

declare(strict_types=1);

const API_BASE_DEFAULT = 'https://platform-api2.max.ru';
const TEXT_LIMIT = 4000;

function fail(string $message): never
{
    fwrite(STDERR, "ОШИБКА: {$message}" . PHP_EOL);
    exit(1);
}

/** Разбор front matter (--- key: value ---) и тела поста. */
function parsePost(string $raw): array
{
    $normalized = str_replace("\xEF\xBB\xBF", '', ltrim($raw));
    if (!preg_match('/^---\r?\n(.*?)\r?\n---\r?\n?(.*)$/s', $normalized, $m)) {
        return [[], trim($normalized)];
    }

    $meta = [];
    foreach (preg_split('/\r?\n/', $m[1]) as $line) {
        $line = trim($line);
        if ($line === '' || str_starts_with($line, '#')) {
            continue;
        }
        if (!str_contains($line, ':')) {
            fail("Некорректная строка front matter: «{$line}»");
        }
        [$key, $value] = array_map('trim', explode(':', $line, 2));
        if ($value === 'true') {
            $value = true;
        } elseif ($value === 'false') {
            $value = false;
        } elseif ($value === '' || $value === 'null') {
            $value = null;
        } elseif ($value[0] === '"') {
            $value = trim($value, '"');
        }
        $meta[$key] = $value;
    }

    return [$meta, trim($m[2])];
}

/** Сохранение поста с обновлённым front matter (тело не меняется). */
function savePost(string $path, array $meta, string $text): void
{
    $lines = ['---'];
    foreach ($meta as $key => $value) {
        $lines[] = sprintf('%s: %s', $key, match (true) {
            is_bool($value) => var_export($value, true),
            $value === null => 'null',
            default => (string) $value,
        });
    }
    file_put_contents($path, implode("\n", $lines) . "\n---\n\n" . $text . "\n");
}

/** Загрузка токенов: slug канала => {token, chat_id, bot_username?}. */
function loadTokens(string $path): array
{
    if (!is_file($path)) {
        fail("Файл токенов не найден: {$path}. Возьмите шаблон local/tokens.example.json.");
    }
    $tokens = json_decode((string) file_get_contents($path), true);
    if (!is_array($tokens)) {
        fail("Файл токенов повреждён (некорректный JSON): {$path}");
    }
    return $tokens;
}

/**
 * Основной скрипт.
 */
$args = array_slice($_SERVER['argv'], 1);
$dryRun = false;
$chatIdOverride = null;
$postPath = null;

foreach ($args as $arg) {
    if ($arg === '--dry-run') {
        $dryRun = true;
    } elseif (str_starts_with($arg, '--chat-id=')) {
        $chatIdOverride = (int) substr($arg, 10);
    } elseif ($postPath === null) {
        $postPath = $arg;
    } else {
        fail("Неизвестный аргумент: {$arg}");
    }
}

if ($postPath === null) {
    fail('Укажите путь к файлу поста. Пример: php bin/post.php channels/ainow/posts/2026-10-29-brauzernye-aiagenty-ustupayut-rabochemu-stolu.md');
}
if (!is_file($postPath)) {
    fail("Файл поста не найден: {$postPath}");
}

[$meta, $text] = parsePost((string) file_get_contents($postPath));

// --- Валидация жизненного цикла (см. AGENTS.md, раздел 3) ---
$status = $meta['status'] ?? 'draft';
if ($status === 'published') {
    fail('Пост уже опубликован (' . basename($postPath) . ').');
}
if ($status !== 'approved') {
    fail("Пост не подтверждён человеком (status: {$status}). Сначала нужно approval — только потом approved.");
}

// --- Канал и токены ---
$repoRoot = dirname(__DIR__);
$tokensPath = getenv('MAX_TOKENS_FILE') ?: ($repoRoot . DIRECTORY_SEPARATOR . 'local' . DIRECTORY_SEPARATOR . 'tokens.json');
$apiBase = rtrim(getenv('MAX_API_BASE') ?: API_BASE_DEFAULT, '/');

$slug = basename(dirname(dirname(realpath($postPath))));
$channel = $meta['channel'] ?? null;
if ($channel !== null && $channel !== $slug) {
    fail("Поле channel ({$channel}) не совпадает с папкой канала ({$slug}).");
}

$tokens = loadTokens($tokensPath);
$creds = $tokens[$slug] ?? null;
if ($creds === null || empty($creds['token'])) {
    fail("В файле токенов нет записи для канала «{$slug}».");
}
$chatId = $chatIdOverride ?? (int) ($creds['chat_id'] ?? 0);
if ($chatId === 0) {
    fail("Для канала «{$slug}» не задан chat_id (можно временно задать опцией --chat-id=N).");
}

// --- Payload ---
$payload = ['text' => $text];
if (in_array($meta['format'] ?? null, ['markdown', 'html'], true)) {
    $payload['format'] = $meta['format'];
}
$payload['notify'] = ($meta['notify'] ?? true) === false ? false : true;   // каналы требуют notify=true
if (($meta['disable_link_preview'] ?? false) === true) {
    $payload['disable_link_preview'] = true;
}

if ($dryRun) {
    echo "DRY-RUN. Ничего не отправлено." . PHP_EOL;
    echo "  URL:     {$apiBase}/messages?chat_id={$chatId}" . PHP_EOL;
    echo "  Токены:  " . str_replace('\\', '/', $tokensPath) . " (конец токена: …" . substr((string) $creds['token'], -6) . ")" . PHP_EOL;
    echo "  Payload: " . json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT) . PHP_EOL;
    exit(0);
}

if (mb_strlen($text) > TEXT_LIMIT) {
    fail("Текст превышает лимит API MAX (" . mb_strlen($text) . " > " . TEXT_LIMIT . " символов).");
}

// --- Отправка ---
$headers = [
    'Authorization: ' . $creds['token'],
    'Content-Type: application/json',
    'Accept: application/json',
];

$ch = curl_init("{$apiBase}/messages?chat_id={$chatId}");
$opts = [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 15,
    CURLOPT_TIMEOUT => 30,
    CURLOPT_HTTPHEADER => $headers,
    CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
];
if (getenv('MAX_CA_CERT')) {
    $opts[CURLOPT_CAINFO] = getenv('MAX_CA_CERT');
}
if (getenv('MAX_INSECURE') === '1') {
    fwrite(STDERR, "ВНИМАНИЕ: проверка TLS отключена (MAX_INSECURE=1)." . PHP_EOL);
    $opts[CURLOPT_SSL_VERIFYPEER] = false;
    $opts[CURLOPT_SSL_VERIFYHOST] = 0;
}
curl_setopt_array($ch, $opts);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$curlError = curl_error($ch);
curl_close($ch);

if ($response === false) {
    fail("Сетевая ошибка: {$curlError}" . (getenv('MAX_CA_CERT') ? '' : ' (если требуется сертификат Минцифры — задайте MAX_CA_CERT)'));
}

$data = json_decode((string) $response, true);
if ($httpCode !== 200 || !is_array($data) || !isset($data['message'])) {
    $detail = is_array($data) ? json_encode($data, JSON_UNESCAPED_UNICODE) : substr((string) $response, 0, 300);
    fail("API вернул {$httpCode}. Ответ: {$detail}");
}

// --- Обновление архива поста ---
$message = $data['message'];
$mid = $message['body']['mid'] ?? null;
$url = $message['url'] ?? null;
$timestampMs = $message['timestamp'] ?? null;
$chatIdActual = $message['recipient']['chat_id'] ?? ($chatIdOverride ?? $creds['chat_id']);

$meta['status'] = 'published';
$meta['message_id'] = $mid;
$meta['channel_id'] = (int) $chatIdActual;
$meta['published_at'] = date('c', $timestampMs === null ? time() : (int) ($timestampMs / 1000));
if (is_string($url) && $url !== '') {
    $meta['url'] = $url;
}
savePost($postPath, $meta, $text);

echo "Опубликовано в MAX." . PHP_EOL;
echo "  Канал:      {$slug} (chat_id {$chatIdActual})" . PHP_EOL;
echo "  message_id: {$mid}" . PHP_EOL;
echo "  Опубликовано: {$meta['published_at']}" . PHP_EOL;
if (is_string($url) && $url !== '') {
    echo "  Ссылка:     {$url}" . PHP_EOL;
}
echo "Файл поста обновлён (status: published)." . PHP_EOL;
