.PHONY: help up down build logs sh migrate createsuperuser collectstatic server-up server-down server-pull server-deploy

help:
	@echo "Targets:"
	@echo "  make up             - start (dev) stack"
	@echo "  make down           - stop stack"
	@echo "  make build          - build images"
	@echo "  make logs           - follow logs"
	@echo "  make sh             - shell into web container"
	@echo "  make migrate        - run migrations"
	@echo "  make createsuperuser- create Django superuser"
	@echo "  make collectstatic  - collect static"
	@echo "  make server-up      - start stack with server overrides"
	@echo "  make server-down    - stop server stack"

up:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

down:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml down

build:
	docker compose -f docker-compose.yml build

logs:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f --tail=200

sh:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web sh

snapshot-dry-run:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py backfill_tx_snapshots --dry-run

snapshot-fill:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py backfill_tx_snapshots

migrate:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py migrate

make-migrations:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py makemigrations

django-shell:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py shell

createsuperuser:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py createsuperuser

collectstatic:
	docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web python manage.py collectstatic --noinput

server-up:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

server-down:
	docker compose -f docker-compose.yml -f docker-compose.prod.yml down


server-pull:
	git pull --ff-only

server-deploy: server-pull
	docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
	docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py migrate
	docker compose -f docker-compose.yml -f docker-compose.prod.yml exec web python manage.py collectstatic --noinput
