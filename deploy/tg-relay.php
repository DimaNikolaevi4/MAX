<?php
/**
 * tg-relay.php — релей публикации в Telegram для репозитория MAX.
 *
 * Ставится на хостинг Beget в ОТДЕЛЬНУЮ папку (не внутри docroot'ов
 * коммерческих сайтов). Рядом создаётся tg-config.php с токеном и секретом:
 *
 *   <?php
 *   return [
 *     'token'  => 'ТОКЕН_ОТ_BOTFATHER',
 *     'secret' => 'ДЛИННАЯ_СЛУЧАЙНАЯ_СТРОКА',
 *   ];
 *
 * Запросы: POST multipart/form-data или JSON:
 *   secret      — обязателен
 *   chat_id     — @username канала или числовой id
 *   text        — HTML-текст (parse_mode=HTML); для sendPhoto это подпись
 *   photo_file  — (multipart) файл изображения; ИЛИ photo — URL картинки
 *   button_url  — URL кнопки под постом (inline keyboard)
 *   button_text — текст кнопки (по умолчанию «Перейти в канал»)
 *   pin         — 1/true: закрепить отправленное сообщение
 *
 * Ответ — сырой JSON Telegram API (в нём result.message_id и entities —
 * они и есть проверка успешной публикации).
 */
header('Content-Type: application/json; charset=utf-8');

$configFile = __DIR__ . '/tg-config.php';
if (!file_exists($configFile)) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'relay: no tg-config.php']);
    exit;
}
$cfg = require $configFile;

$in = $_POST;
if (!$in) {
    $in = json_decode(file_get_contents('php://input'), true) ?: [];
}
if (($in['secret'] ?? '') !== $cfg['secret']) {
    http_response_code(403);
    echo json_encode(['ok' => false, 'error' => 'relay: bad secret']);
    exit;
}
$chatId = $in['chat_id'] ?? '';
if (!$chatId) {
    http_response_code(400);
    echo json_encode(['ok' => false, 'error' => 'relay: no chat_id']);
    exit;
}

// служебное действие: удаление сообщения (тестовые посты, исправления)
if (($in['action'] ?? '') === 'delete') {
    $ch = curl_init('https://api.telegram.org/bot' . $cfg['token'] . '/deleteMessage');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => ['chat_id' => $chatId, 'message_id' => (int)($in['message_id'] ?? 0)],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $out = curl_exec($ch);
    $err = curl_error($ch);
    curl_close($ch);
    echo $out !== false ? $out : json_encode(['ok' => false, 'error' => 'relay: curl: ' . $err]);
    exit;
}

$hasFile = !empty($_FILES['photo_file']['tmp_name']) && is_uploaded_file($_FILES['photo_file']['tmp_name']);
$method = ($hasFile || !empty($in['photo'])) ? 'sendPhoto' : 'sendMessage';

$params = ['chat_id' => $chatId, 'parse_mode' => 'HTML'];
if ($method === 'sendPhoto') {
    $params['caption'] = $in['text'] ?? '';
    if ($hasFile) {
        $params['photo'] = new CURLFile($_FILES['photo_file']['tmp_name'], $_FILES['photo_file']['type'] ?: 'image/png', 'card.png');
    } else {
        $params['photo'] = $in['photo'];
    }
    if (isset($in['caption_above'])) {
        $params['show_caption_above_media'] = !empty($in['caption_above']);
    }
} else {
    $params['text'] = $in['text'] ?? '';
    $params['disable_web_page_preview'] = true;
}
if (!empty($in['button_url'])) {
    $params['reply_markup'] = json_encode([
        'inline_keyboard' => [[
            ['text' => $in['button_text'] ?? 'Перейти в канал', 'url' => $in['button_url']],
        ]],
    ]);
}

$ch = curl_init('https://api.telegram.org/bot' . $cfg['token'] . '/' . $method);
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $params,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 30,
]);
$out = curl_exec($ch);
$err = curl_error($ch);
curl_close($ch);

if ($out === false) {
    http_response_code(502);
    echo json_encode(['ok' => false, 'error' => 'relay: curl: ' . $err]);
    exit;
}
$resp = json_decode($out, true);

// опциональное закрепление отправленного сообщения
if (!empty($in['pin']) && is_array($resp) && !empty($resp['ok'])) {
    $mid = $resp['result']['message_id'] ?? null;
    if ($mid) {
        $ch = curl_init('https://api.telegram.org/bot' . $cfg['token'] . '/pinChatMessage');
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => ['chat_id' => $chatId, 'message_id' => $mid],
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 20,
        ]);
        curl_exec($ch);
        curl_close($ch);
    }
}

echo $out;
