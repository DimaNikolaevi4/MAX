<?php
/**
 * review.php — отправка черновика поста на согласование в личную переписку
 * с ботом (канал согласования). Пост показывается человеку ровно так,
 * как он будет выглядеть в мессенджере.
 *
 * Использование:
 *   php bin/review.php <путь-к-посту.md>            — отправить черновик на согласование
 *   php bin/review.php <путь-к-посту.md> --dry-run — показать, что будет отправлено
 *   php bin/review.php <путь-к-посту.md> --note="Комментарий" — добавить примечание
 *
 * Куда отправлять: поле review_chat_id в local/tokens.json (диалог человека
 * с ботом). Переопределить: --chat-id=N или переменная MAX_REVIEW_CHAT_ID.
 *
 * Статус поста НЕ меняется. После одобрения человеком агент ставит
 * status: approved и публикует через bin/post.php. См. AGENTS.md.
 */

declare(strict_types=1);

const API_BASE_DEFAULT = 'https://platform-api2.max.ru';

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

$args = array_slice($_SERVER['argv'], 1);
$dryRun = false;
$chatIdOverride = null;
$note = null;
$postPath = null;

foreach ($args as $arg) {
    if ($arg === '--dry-run') {
        $dryRun = true;
    } elseif (str_starts_with($arg, '--chat-id=')) {
        $chatIdOverride = (int) substr($arg, 10);
    } elseif (str_starts_with($arg, '--note=')) {
        $note = substr($arg, 7);
    } elseif ($postPath === null) {
        $postPath = $arg;
    } else {
        fail("Неизвестный аргумент: {$arg}");
    }
}

if ($postPath === null) {
    fail('Укажите путь к файлу поста. Пример: php bin/review.php channels/ainow/posts/2026-11-01-moi-post.md');
}
if (!is_file($postPath)) {
    fail("Файл поста не найден: {$postPath}");
}

[$meta, $text] = parsePost((string) file_get_contents($postPath));

$status = $meta['status'] ?? 'draft';
if ($status !== 'draft') {
    fail("На согласование отправляются посты в статусе draft (сейчас: {$status}).");
}

$slug = basename(dirname(dirname(realpath($postPath))));
$channel = $meta['channel'] ?? null;
if ($channel !== null && $channel !== $slug) {
    fail("Поле channel ({$channel}) не совпадает с папкой канала ({$slug}).");
}

$tokensPath = getenv('MAX_TOKENS_FILE') ?: (dirname(__DIR__) . DIRECTORY_SEPARATOR . 'local' . DIRECTORY_SEPARATOR . 'tokens.json');
$apiBase = rtrim(getenv('MAX_API_BASE') ?: API_BASE_DEFAULT, '/');

$tokens = json_decode((string) file_get_contents($tokensPath), true);
$creds = $tokens[$slug] ?? null;
if ($creds === null || empty($creds['token'])) {
    fail("В файле токенов нет записи для канала «{$slug}».");
}
$reviewChatId = $chatIdOverride
    ?? (int) (getenv('MAX_REVIEW_CHAT_ID') ?: ($creds['review_chat_id'] ?? 0));
if ($reviewChatId === 0) {
    fail("Для канала «{$slug}» не задан review_chat_id (диалог человека с ботом).");
}

$header = "📋 ЧЕРНОВИК ПОСТА для канала «{$slug}»";
if (isset($meta['edit_of'])) {
    $header .= "\n✏️ ПРАВКА поста: {$meta['edit_of']}";
}
if ($note !== null) {
    $header .= "\n💬 Примечание автора: {$note}";
}
$footer = "\n\n—\n✅ Ответьте «ок» — опубликую как есть.\n✏️ Напишите правки — исправлю и пришлю заново.";

$payload = [
    'text' => $header . "\n\n" . $text . $footer,
    'format' => 'markdown',
    'notify' => true,
];

if ($dryRun) {
    echo "DRY-RUN. Ничего не отправлено." . PHP_EOL;
    echo "  Куда: диалог с ботом, chat_id {$reviewChatId}" . PHP_EOL;
    echo "  Текст:" . PHP_EOL . ($payload['text']) . PHP_EOL;
    exit(0);
}

$ch = curl_init("{$apiBase}/messages?chat_id={$reviewChatId}");
$opts = [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 15,
    CURLOPT_TIMEOUT => 30,
    CURLOPT_HTTPHEADER => [
        'Authorization: ' . $creds['token'],
        'Content-Type: application/json',
        'Accept: application/json',
    ],
    CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
];
if (getenv('MAX_CA_CERT')) {
    $opts[CURLOPT_CAINFO] = getenv('MAX_CA_CERT');
}
curl_setopt_array($ch, $opts);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
$curlError = curl_error($ch);
curl_close($ch);

if ($response === false) {
    fail("Сетевая ошибка: {$curlError}");
}
$data = json_decode((string) $response, true);
if ($httpCode !== 200 || !is_array($data)) {
    $detail = is_array($data) ? json_encode($data, JSON_UNESCAPED_UNICODE) : substr((string) $response, 0, 300);
    fail("API вернул {$httpCode}. Ответ: {$detail}");
}

echo "Черновик отправлен на согласование (диалог chat_id {$reviewChatId})." . PHP_EOL;
echo "Ждём ответ человека: «ок» или правки (см. GET /updates, событие message_created)." . PHP_EOL;
