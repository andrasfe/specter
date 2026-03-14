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
COPY --from=build /app/target/cotrn00c-1.0-SNAPSHOT.jar app.jar
COPY sql/ /app/sql/
# Default: batch mode (Main). For interactive terminal:
#   docker compose run -it app java -cp app.jar com.specter.generated.TerminalMain
ENTRYPOINT ["java", "-jar", "app.jar"]
