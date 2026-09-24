# OpenFlux Custom — unsigned IPA builder

Этот маленький репозиторий **не содержит исходники OpenFlux**. GitHub Actions при запуске сам скачивает актуальный `p1neappleXpress/OpenFlux`, добавляет функцию **«всё через VPN, выбранные домены напрямую»**, собирает iOS-приложение без подписи и отдаёт `OpenFlux-Custom-unsigned.ipa` как Artifact.

## Что добавляется

- весь IPv4-трафик по умолчанию остаётся в OpenFlux;
- в интерфейсе появляется круглая кнопка **«Прямые сайты»**;
- домены/IP вводятся по одному на строку;
- при следующем подключении VPN домены резолвятся в IPv4 и их адреса добавляются в `excludedRoutes`;
- всё, чего нет в списке, остаётся в VPN.

> Важно: это первая версия. Маршрутизация идёт по IP, полученным при подключении VPN. Если CDN сменит IP, переподключи VPN. Поддомены (`api.example.com`) добавляются отдельно.

## Как получить IPA с Windows

1. Создай пустой репозиторий на GitHub, например `openflux-custom-builder`.
2. Загрузи в него содержимое этого ZIP **с сохранением папки `.github/workflows/`**.
3. Открой вкладку **Actions** → `Build OpenFlux Custom unsigned IPA` → **Run workflow**.
4. После завершения открой запуск Actions и скачай Artifact `OpenFlux-Custom-unsigned`.
5. Внутри будет `OpenFlux-Custom-unsigned.ipa`.

## Подпись

Unsigned IPA сама по себе на iPhone не установится. При переподписании должны быть подписаны **оба** bundle:

- `Payload/OpenFlux.app/PlugIns/OpenFluxTunnel.appex` — сначала;
- `Payload/OpenFlux.app` — затем.

Для работающего VPN профиль расширения должен разрешать Network Extension / `packet-tunnel-provider`. Обычный сертификат без такого entitlement может подписать IPA формально, но туннель не запустится.

При смене Bundle ID основной app и tunnel extension должны получать совместимые App ID/provisioning profiles.

## Режим DIRECT

Например список:

```text
vk.com
api.vk.com
yandex.ru
max.ru
```

означает: IP этих имён идут напрямую через обычное подключение iPhone; остальное идёт через OpenFlux.
