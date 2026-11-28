<?php
/**
 * Валидатор текста na100 на хостинге — подмножество shared/format_core.py §0.
 * CLI: php na100_validator.php <файл.txt|пост.md>   -> JSON с ошибками/предупреждениями.
 */
declare(strict_types=1);

require_once __DIR__ . '/na100_config.php';

function na100_blocks(string $text): array
{
    return preg_split('/\n\s*\n/u', trim($text)) ?: [];
}

function na100_is_subhead(string $line): bool
{
    return (bool) preg_match('/^[1-5]\x{FE0F}?\x{20E3}\s+\*\*[^*]+\*\*$/u', trim($line));
}

function na100_validate(string $text, array $cfg): array
{
    $errors = [];
    $warnings = [];
    $text = str_replace("\r\n", "\n", $text);
    $len = mb_strlen($text, 'UTF-8');
    if ($len > 4000) {
        $errors[] = "LENGTH: {$len} > 4000";
    } elseif ($len > 3600) {
        $warnings[] = "LENGTH_SOFT: {$len} > 3600";
    }

    $lines = preg_split('/\R/u', $text) ?: [];
    $meaningful = [];
    foreach ($lines as $i => $ln) {
        if (trim($ln) !== '') {
            $meaningful[] = [$i, $ln];
        }
    }
    if (!$meaningful) {
        return [['HEADLINE: нет текста'], []];
    }
    [$firstIdx, $firstLine] = $meaningful[0];
    if (!preg_match('/^\*\*([^*]+)\*\*$/u', trim($firstLine), $m)) {
        $errors[] = 'HEADLINE: первая строка должна быть **Заголовок**';
    } else {
        $title = trim($m[1]);
        if (mb_strlen($title, 'UTF-8') > 60) {
            $errors[] = 'HEADLINE_LEN: заголовок > 60';
        }
        if (substr($title, -1) === '.') {
            $errors[] = 'HEADLINE_DOT: заголовок заканчивается точкой';
        }
    }
    if (isset($lines[$firstIdx + 1]) && trim($lines[$firstIdx + 1]) !== '') {
        $errors[] = 'AIR_HEADLINE: нет пустой строки после заголовка';
    }

    foreach ($lines as $ln) {
        if (preg_match('/^\s*(?:[-*+]|\d+\.)\s+/u', $ln)) {
            $errors[] = 'MARKUP_LIST: markdown-список';
        }
        if (preg_match('/^\s*\|.*\|/u', $ln)) {
            $errors[] = 'MARKUP_TABLE: таблица';
        }
        if (preg_match('/^\s*#{1,6}\s+/u', $ln)) {
            $errors[] = 'MARKUP_HEAD: ###';
        }
        if (strpos($ln, '`') !== false) {
            $errors[] = 'MARKUP_TICK: backtick';
        }
    }

    $blocks = na100_blocks($text);
    $ctaIdx = null;
    $cta = null;
    foreach ($blocks as $i => $block) {
        foreach (preg_split('/\R/u', $block) ?: [] as $line) {
            if (preg_match('/^>\s*\*\*Подписывайтесь на \[([^\]]+)\]\(([^)\s]+)\)\*\*\s*—\s*(.+)$/u',
                           trim($line), $m)) {
                $ctaIdx = $i;
                $cta = $m;
                break 2;
            }
        }
    }
    if (!$cta) {
        $errors[] = 'CTA_FORMAT: нет CTA-цитаты со ссылкой';
    } else {
        if (!in_array($cta[2], [$cfg['cta_url'], $cfg['ainow_url']], true)) {
            $errors[] = 'CTA_TARGET_URL: ссылка не адресату';
        }
        if (trim($cta[3]) === '') {
            $errors[] = 'CTA_PHRASE: пустая фраза';
        }
        $last = count($blocks) - 1;
        $reactionBetween = ($last >= $ctaIdx + 2
            && count(preg_split('/\R/u', $blocks[$ctaIdx + 1]) ?: []) === 1
            && preg_match('/реакц|🔥|поставьте|ставьте|жмите|лайк/ui', $blocks[$ctaIdx + 1]));
        $want = $last - ($reactionBetween ? 2 : 1);
        if ($ctaIdx !== $want) {
            $errors[] = 'CTA_POSITION: CTA должен быть предпоследним блоком';
        }
        $question = trim($blocks[$last] ?? '');
        if (!preg_match('/\?$/u', $question) || strpos($question, "\n") !== false) {
            $errors[] = 'QUESTION: последний блок — одна строка с ?';
        } elseif (preg_match('/провер(ить|или|ьте)/ui', $question)) {
            $warnings[] = 'QUESTION_WORDING: лучше без «проверить/проверили»';
        }
    }

    $subs = [];
    $items = [];
    $current = null;
    foreach ($lines as $ln) {
        $t = trim($ln);
        if ($t === '') {
            continue;
        }
        if (preg_match('/^[1-5]\x{FE0F}?\x{20E3}\s+\*\*(.+?)\*\*$/u', $t, $m)) {
            $subs[] = $m[1];
            $current = $t;
            $items[] = '';
            continue;
        }
        if ($current !== null) {
            $items[count($items) - 1] .= $t . "\n";
        }
    }
    if (count($items) !== 5) {
        $errors[] = 'DIGEST_ITEMS: пунктов ' . count($items) . ', нужно 5';
    }
    $digits = 0;
    foreach ($subs as $s) {
        if (preg_match('/\d/u', $s)) {
            $digits++;
        }
    }
    if ($digits < 2) {
        $errors[] = 'DIGEST_DIGITS: цифр в подзаголовках ' . $digits . ', нужно >=2';
    }
    foreach ($items as $n => $item) {
        if (mb_strlen($item, 'UTF-8') > 750) {
            $errors[] = 'DIGEST_ITEM_LEN: пункт ' . ($n + 1) . ' > 750';
        }
    }
    if (substr_count($text, 'Что случилось') !== 5
        || substr_count($text, 'Почему важно') !== 5) {
        $errors[] = 'DIGEST_STRUCTURE: нужно по 5 «Что случилось» и «Почему важно»';
    }
    if (strpos($text, 'Итог дня') === false) {
        $errors[] = 'DIGEST_SUMMARY: нет «Итог дня»';
    }

    // Внешние ссылки: только CTA
    preg_match_all('/\[[^\]]+\]\((https?:\/\/[^)\s]+)\)/u', $text, $links);
    foreach ($links[1] as $url) {
        if (!in_array($url, [$cfg['cta_url'], $cfg['ainow_url']], true)) {
            $errors[] = 'NA100_LINKS: внешняя ссылка ' . $url;
        }
    }

    // Запрещённые организации
    $forbidden = @json_decode((string) @file_get_contents($cfg['forbidden_file']), true);
    foreach (($forbidden['patterns'] ?? []) as $p) {
        $pat = is_array($p) ? (string) ($p['pattern'] ?? '') : (string) $p;
        if ($pat === '') {
            continue;
        }
        $rx = strpos($pat, 're:') === 0 ? substr($pat, 3) : preg_quote($pat, '/');
        if (preg_match('/' . $rx . '/ui', $text)) {
            $errors[] = 'FORBIDDEN_ORG: ' . $pat;
        }
    }

    return [$errors, $warnings];
}

if (PHP_SAPI === 'cli' && isset($argv[1])) {
    $raw = (string) @file_get_contents($argv[1]);
    if (preg_match('/\A---\R.*?\R---\R?/us', $raw, $m)) {
        $raw = substr($raw, strlen($m[0]));
    }
    [$errors, $warnings] = na100_validate($raw, na100_config());
    echo json_encode(['errors' => $errors, 'warnings' => $warnings,
                      'ok' => count($errors) === 0], JSON_UNESCAPED_UNICODE) . "\n";
}
