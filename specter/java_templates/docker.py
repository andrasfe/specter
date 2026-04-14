"""Docker deployment templates for generated Specter Java projects.

Templates for Dockerfile and docker-compose.yml using Python
``str.format`` placeholders.
"""

# ---------------------------------------------------------------------------
# Dockerfile
# ---------------------------------------------------------------------------

DOCKERFILE = """\
# Stage 1: Build
FROM maven:3.9-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
RUN mvn dependency:go-offline -B
COPY src ./src
RUN mvn package -DskipTests -B

# Stage 2: Runtime
FROM eclipse-temurin:17-jre-alpine
WORKDIR /app
COPY --from=build /app/target/{artifact_id}-1.0-SNAPSHOT.jar app.jar
COPY sql/ /app/sql/
# Default: batch mode (Main). For interactive terminal:
#   docker compose run -it app java -cp app.jar com.specter.generated.TerminalMain
ENTRYPOINT ["java", "-jar", "app.jar"]
"""

# ---------------------------------------------------------------------------
# docker-compose.yml
# ---------------------------------------------------------------------------

DOCKER_COMPOSE_YML = """\
version: "3.9"

services:
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: specter
      POSTGRES_USER: specter
      POSTGRES_PASSWORD: specter
    ports:
      - "5432:5432"
    volumes:
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U specter"]
      interval: 5s
      timeout: 3s
      retries: 10

  rabbitmq:
    image: rabbitmq:3-management
    environment:
      RABBITMQ_DEFAULT_USER: specter
      RABBITMQ_DEFAULT_PASS: specter
    ports:
      - "5672:5672"
      - "15672:15672"
    healthcheck:
      test: ["CMD-SHELL", "rabbitmq-diagnostics -q ping"]
      interval: 5s
      timeout: 5s
      retries: 12

  wiremock:
    image: wiremock/wiremock:3.5.4
    command: ["--global-response-templating", "--verbose"]
    ports:
      - "8080:8080"
    volumes:
      - ./wiremock/mappings:/home/wiremock/mappings
      - ./wiremock/__files:/home/wiremock/__files
    healthcheck:
      test: ["CMD-SHELL", "wget -q -O- http://localhost:8080/__admin/health || exit 0"]
      interval: 5s
      timeout: 3s
      retries: 10

  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      wiremock:
        condition: service_started
    environment:
      SPECTER_DB_URL: jdbc:postgresql://db:5432/specter
      SPECTER_DB_USER: specter
      SPECTER_DB_PASSWORD: specter
      SPECTER_AMQP_HOST: rabbitmq
      SPECTER_AMQP_PORT: "5672"
      SPECTER_AMQP_USER: specter
      SPECTER_AMQP_PASSWORD: specter
      SPECTER_AMQP_VHOST: "/"
      SPECTER_CALL_BASE_URL: http://wiremock:8080

  terminal:
    build: .
    stdin_open: true
    tty: true
    entrypoint: ["java", "-cp", "app.jar", "com.specter.generated.TerminalMain"]
    depends_on:
      db:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
      wiremock:
        condition: service_started
    environment:
      SPECTER_DB_URL: jdbc:postgresql://db:5432/specter
      SPECTER_DB_USER: specter
      SPECTER_DB_PASSWORD: specter
      SPECTER_AMQP_HOST: rabbitmq
      SPECTER_AMQP_PORT: "5672"
      SPECTER_AMQP_USER: specter
      SPECTER_AMQP_PASSWORD: specter
      SPECTER_AMQP_VHOST: "/"
      SPECTER_CALL_BASE_URL: http://wiremock:8080
"""
