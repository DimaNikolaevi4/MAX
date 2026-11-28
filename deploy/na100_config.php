<?php
/**
 * Конфигурация утреннего выпуска na100 на хостинге.
 * Секреты НЕ лежат в репозитории: читаются из /0s3/blogger-data/.
 */
declare(strict_types=1);

function na100_config(): array
{
    $data = '/0s3/blogger-data';
    return [
        'data_dir' => $data,
        'queue_dir' => $data . '/na100',
        'state_file' => $data . '/state/na100_state.json',
        'media_dir' => $data . '/media/na100',
        'token_file' => $data . '/na100_token.txt',
        'chat_id' => -76927529477469,
        'cloudflare_token_file' => $data . '/cloudflare-token.txt',
        'cloudflare_account_file' => $data . '/cloudflare-account.txt',
        'cloudflare_model' => '@cf/openai/gpt-oss-120b',
        'forbidden_file' => $data . '/forbidden_orgs.json',
        'publish_time' => '07:30',
        'cta_url' => 'https://max.ru/channel_na100',
        'cta_label' => 'Новости технологий ИИ, нейросетей и инноваций',
        'ainow_url' => 'https://max.ru/channel_ainow',
        'ainow_label' => 'AI',
    ];
}

function na100_secret(string $path): string
{
    $value = is_file($path) ? trim((string) file_get_contents($path)) : '';
    if ($value === '') {
        throw new RuntimeException('нет секретного файла: ' . basename($path));
    }
    return $value;
}
