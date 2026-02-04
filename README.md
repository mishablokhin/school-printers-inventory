# School Cartridges SSO (каркас)

Минимальный каркас Django-приложения с авторизацией через Nextcloud по OpenID Connect (H2CK/oidc):
- страница входа
- страница пользователя (ФИО из Nextcloud)
- выход

## Быстрый старт (локально)

1) Скопируй переменные окружения:

```bash
cp .env .env
```

2) Заполни:
- `OIDC_SERVER_URL`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`

3) Запусти:

```bash
make up
```

Открой: http://localhost:8000

## Callback URL (важно)

В `django-allauth` callback для OIDC-провайдера с `provider_id=nextcloud`:

```
/accounts/oidc/nextcloud/login/callback/
```

## Сервер (Docker + Caddy)

- Скопируй `.env` на сервер и выставь `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `APP_BASE_URL=https://...`
- Запуск:

```bash
make server-up
```

Caddyfile лежит в `deploy/Caddyfile`.
