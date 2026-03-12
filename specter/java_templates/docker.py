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

  activemq:
    image: apache/activemq-artemis:2.31.2
    environment:
      ARTEMIS_USER: admin
      ARTEMIS_PASSWORD: admin
    ports:
      - "61616:61616"
      - "8161:8161"
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:8161 || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 10

  app:
    build: .
    depends_on:
      db:
        condition: service_healthy
      activemq:
        condition: service_healthy
    environment:
      SPECTER_DB_URL: jdbc:postgresql://db:5432/specter
      SPECTER_DB_USER: specter
      SPECTER_DB_PASSWORD: specter
      SPECTER_JMS_URL: tcp://activemq:61616

  terminal:
    build: .
    stdin_open: true
    tty: true
    entrypoint: ["java", "-cp", "app.jar", "com.specter.generated.TerminalMain"]
    depends_on:
      db:
        condition: service_healthy
      activemq:
        condition: service_healthy
    environment:
      SPECTER_DB_URL: jdbc:postgresql://db:5432/specter
      SPECTER_DB_USER: specter
      SPECTER_DB_PASSWORD: specter
      SPECTER_JMS_URL: tcp://activemq:61616
"""
