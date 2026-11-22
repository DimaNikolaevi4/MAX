<?php
/**
 * stats_cron.php — сбор статистики каналов MAX на хостинге (снапшоты).
 *
 * Вызывается из post_cron.php в 07:45-запуске (после всех публикаций),
 * либо напрямую CLI: php stats_cron.php.
 *
 * По каждому каналу:
 *   * GET /chats/{chat_id} — подписчики, число сообщений;
 *   * GET /messages?chat_id=...&count=100 — просмотры каждого поста (stat.views);
 *   * снимок: /0s3/blogger-data/stats/<канал>-<YYYY-MM-DD>.json (один на день);
 *   * сравнение с предыдущим снимком: прирост подписчиков, новые посты,
 *     прирост просмотров (топ-5) — отчёт в stdout (лог) и
 *     /0s3/blogger-data/stats/report-<канал>-<YYYY-MM-DD>.txt.
 *
 * ВАЖНО: /updates здесь НЕ вызывается (подписки/отписки — из локального
 * журнала poll digest_bot.py; единственный консьюмер /updates — он).
 *
 * Не трогать чужие каталоги хостинга.
 */

declare(strict_types=1);

date_default_timezone_set('Europe/Moscow');

const API_BASE = 'https://platform-api2.max.ru';

function statsChannels(string $dataDir): array
{
    return [
        'ainow' => ['chat_id' => -76964086179165, 'token_file' => $dataDir . '/ainow_token.txt'],
        'na100' => ['chat_id' => -76927529477469, 'token_file' => $dataDir . '/na100_token.txt'],
        'zabava' => ['chat_id' => -71021572420957, 'token_file' => $dataDir . '/zabava_token.txt'],
        'catden' => ['chat_id' => -81170615067997, 'token_file' => $dataDir . '/catden_token.txt'],
    ];
}

function statsRunAll(string $dataDir, bool $dry = false): void
{
    $statsDir = $dataDir . '/stats';
    if (!is_dir($statsDir) && !@mkdir($statsDir, 0775, true)) {
        statsLog("FAIL: не создать $statsDir");
        return;
    }
    foreach (statsChannels($dataDir) as $slug => $conf) {
        statsChannel($slug, $conf, $statsDir, $dry);
    }
    statsLog('=== статистика собрана');
}

function statsChannel(string $slug, array $conf, string $statsDir, bool $dry): void
{
    $now = new DateTimeImmutable('now', new DateTimeZone('Europe/Moscow'));
    $token = is_file($conf['token_file'])
        ? trim((string) file_get_contents($conf['token_file']))
        : '';
    if ($token === '') {
        statsLog("[$slug] FAIL: токен не найден ({$conf['token_file']})");
        return;
    }

    $chat = statsApi($token, '/chats/' . (int) $conf['chat_id']);
    if (!is_array($chat)) {
        statsLog("[$slug] FAIL chats API");
        return;
    }
    $c = $chat['chat'] ?? $chat;
    $msgsRaw = statsApi($token, '/messages?chat_id=' . (int) $conf['chat_id'] . '&count=100');
    $msgs = is_array($msgsRaw) ? ($msgsRaw['messages'] ?? []) : [];
    if (!$msgs && $msgsRaw === null) {
        statsLog("[$slug] FAIL messages API");
        return;
    }

    $posts = [];
    foreach ($msgs as $m) {
        $body = $m['body'] ?? [];
        $ts = $m['timestamp'] ?? 0;
        $dt = $ts ? (new DateTimeImmutable('@' . ($ts / 1000)))
            ->setTimezone(new DateTimeZone('Europe/Moscow')) : null;
        $text = (string) ($body['text'] ?? '');
        $title = '';
        foreach (preg_split('/\r?\n/', $text) as $line) {
            if (trim($line) !== '') {
                $title = trim($line);
                break;
            }
        }
        $posts[] = [
            'mid' => (string) ($body['mid'] ?? ''),
            'dt' => $dt ? $dt->format(DATE_ATOM) : '',
            'views' => $m['stat']['views'] ?? null,
            'len' => mb_strlen($text),
            'attachments' => array_map(
                static fn($a) => $a['type'] ?? null, $body['attachments'] ?? []),
            'url' => (string) ($m['url'] ?? ''),
            'title' => $title,
        ];
    }
    usort($posts, static fn($a, $b) => strcmp($a['dt'], $b['dt']));

    $snap = [
        'taken_at' => $now->format(DATE_ATOM),
        'channel' => $slug,
        'title' => $c['title'] ?? null,
        'status' => $c['status'] ?? null,
        'participants' => $c['participants_count'] ?? null,
        'messages_count' => $c['messages_count'] ?? null,
        'posts' => $posts,
    ];
    $snapPath = $statsDir . '/' . $slug . '-' . $now->format('Y-m-d') . '.json';
    if ($dry) {
        statsLog(sprintf('[%s] [dry] подписчиков: %s, сообщений: %s (снимок не пишется)',
            $slug, (string) $snap['participants'], (string) $snap['messages_count']));
        return;
    }
    file_put_contents($snapPath, json_encode($snap, JSON_UNESCAPED_UNICODE | JSON_PRETTY_PRINT));

    $lines = [
        sprintf('снимок: %s, канал: %s (%s)', $now->format('Y-m-d H:i'), (string) $snap['title'], $slug),
        sprintf('подписчиков: %s, сообщений: %s', (string) $snap['participants'], (string) $snap['messages_count']),
    ];

    // предыдущий снимок (строго раньше сегодня)
    $prev = null;
    $prevAt = null;
    foreach (glob($statsDir . '/' . $slug . '-*.json') ?: [] as $f) {
        $j = json_decode((string) file_get_contents($f), true);
        if (!is_array($j) || empty($j['taken_at'])) {
            continue;
        }
        $at = DateTimeImmutable::createFromFormat(DATE_ATOM, $j['taken_at']);
        if (!$at || $at->format('Y-m-d') >= $now->format('Y-m-d')) {
            continue;
        }
        if ($prevAt === null || $at > $prevAt) {
            $prev = $j;
            $prevAt = $at;
        }
    }

    if ($prev) {
        $hours = max(($now->getTimestamp() - $prevAt->getTimestamp()) / 3600, 0.1);
        $dp = (int) $snap['participants'] - (int) $prev['participants'];
        $span = ($hours >= 20 && $hours <= 28) ? 'сутки' : sprintf('%.1f ч', $hours);
        $lines[] = sprintf('период: %s → %s (%s)',
            $prevAt->format('Y-m-d H:i'), $now->format('Y-m-d H:i'), $span);
        $lines[] = sprintf('подписчики за период: %+d (было %s, стало %s)',
            $dp, (string) $prev['participants'], (string) $snap['participants']);

        $old = [];
        foreach (($prev['posts'] ?? []) as $p) {
            $old[$p['mid']] = $p;
        }
        $newPosts = array_values(array_filter($posts, static fn($p) => !isset($old[$p['mid']])));
        if ($newPosts) {
            $lines[] = '';
            $lines[] = 'новые посты за период:';
            foreach ($newPosts as $p) {
                $lines[] = sprintf('  %s просм.  %s',
                    $p['views'] ?? '-', mb_substr($p['title'], 0, 70));
            }
        }
        $gains = [];
        foreach ($posts as $p) {
            $o = $old[$p['mid']] ?? null;
            if ($o === null || !is_int($p['views']) || !is_int($o['views'] ?? null)) {
                continue;
            }
            $gains[] = [$p['views'] - $o['views'], $p];
        }
        usort($gains, static fn($a, $b) => $b[0] <=> $a[0]);
        if ($gains) {
            $lines[] = '';
            $lines[] = 'прирост просмотров за период (топ-5):';
            foreach (array_slice($gains, 0, 5) as [$delta, $p]) {
                $lines[] = sprintf('  %+d  %d  %s  %s',
                    $delta, (int) $p['views'], mb_substr((string) $p['dt'], 0, 10), mb_substr($p['title'], 0, 60));
            }
        }
    } else {
        $lines[] = 'предыдущих снимков нет — это база для будущей динамики';
    }

    $views = array_values(array_filter(array_column($posts, 'views'), 'is_int'));
    if ($views) {
        sort($views);
        $n = count($views);
        $median = $n % 2 ? $views[intdiv($n, 2)]
            : (int) (($views[$n / 2 - 1] + $views[$n / 2]) / 2);
        $lines[] = '';
        $lines[] = sprintf('просмотры (накопленные): min=%d, median=%d, max=%d',
            $views[0], $median, $views[$n - 1]);
    }
    $lines[] = 'снимок сохранён: stats/' . basename($snapPath);

    $reportPath = $statsDir . '/report-' . $slug . '-' . $now->format('Y-m-d') . '.txt';
    file_put_contents($reportPath, implode("\n", $lines) . "\n");
    statsLog("[$slug] OK: " . basename($snapPath));
    foreach ($lines as $l) {
        statsLog("[$slug] | $l");
    }
}

/** GET JSON к API MAX (CA-бандл с FTP). Возвращает массив или null. */
function statsApi(string $token, string $path): ?array
{
    $ch = curl_init(API_BASE . $path);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 15,
        CURLOPT_TIMEOUT => 60,
        CURLOPT_USERAGENT => 'curl/8.13.0',
        CURLOPT_HTTPHEADER => ['Authorization: ' . $token],
        CURLOPT_CAINFO => CA_INFO(),
    ]);
    $resp = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($resp === false || $code !== 200) {
        statsLog("API fail: HTTP $code $err ($path)");
        return null;
    }
    $data = json_decode((string) $resp, true);
    return is_array($data) ? $data : null;
}

function statsLog(string $msg): void
{
    echo '[' . date('H:i:s') . '] ' . $msg . "\n";
}

// CA-бандл: в контексте post_cron.php функция уже определена, при прямом
// запуске CLI — определяем здесь (путь относительно каталога скрипта).
if (!function_exists('CA_INFO')) {
    function CA_INFO(): string
    {
        return dirname(__DIR__) . '/blogger-data/russian_ca_bundle.pem';
    }
}

// Прямой запуск CLI: php stats_cron.php (данные берём относительно скрипта).
if (PHP_SAPI === 'cli' && realpath($_SERVER['argv'][0] ?? '') === __FILE__) {
    $dataDir = dirname(__DIR__) . '/blogger-data';
    statsRunAll($dataDir, in_array('--dry', $_SERVER['argv'] ?? [], true));
}
