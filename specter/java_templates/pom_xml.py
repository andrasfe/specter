"""Maven pom.xml template for generated Specter Java projects.

The template uses Python ``str.format`` placeholders:
- ``{group_id}``     -- Maven group ID (e.g. ``com.example``)
- ``{artifact_id}``  -- Maven artifact ID (e.g. ``cobol-program``)
- ``{program_name}`` -- Human-readable program name for ``<name>``
- ``{main_class}``   -- Fully qualified Main class for shade plugin
"""

POM_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0
                             http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <groupId>{group_id}</groupId>
    <artifactId>{artifact_id}</artifactId>
    <version>1.0-SNAPSHOT</version>
    <packaging>jar</packaging>

    <name>{program_name}</name>
    <description>Generated COBOL-to-Java translation by Specter</description>

    <properties>
        <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
        <maven.compiler.source>17</maven.compiler.source>
        <maven.compiler.target>17</maven.compiler.target>
        <junit.version>5.10.2</junit.version>
        <lanterna.version>3.1.1</lanterna.version>
        <mockito.version>5.11.0</mockito.version>
        <amqp.client.version>5.21.0</amqp.client.version>
        <httpclient5.version>5.3.1</httpclient5.version>
    </properties>

    <dependencies>
        <!-- JUnit Jupiter (test scope) -->
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-api</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-engine</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.junit.jupiter</groupId>
            <artifactId>junit-jupiter-params</artifactId>
            <version>${{junit.version}}</version>
            <scope>test</scope>
        </dependency>

        <!-- Lanterna terminal UI -->
        <dependency>
            <groupId>com.googlecode.lanterna</groupId>
            <artifactId>lanterna</artifactId>
            <version>${{lanterna.version}}</version>
        </dependency>

        <!-- PostgreSQL JDBC driver -->
        <dependency>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
            <version>42.7.2</version>
        </dependency>

        <!-- HikariCP connection pooling -->
        <dependency>
            <groupId>com.zaxxer</groupId>
            <artifactId>HikariCP</artifactId>
            <version>5.1.0</version>
        </dependency>

        <!-- RabbitMQ AMQP client (replaces ActiveMQ Artemis / JMS) -->
        <dependency>
            <groupId>com.rabbitmq</groupId>
            <artifactId>amqp-client</artifactId>
            <version>${{amqp.client.version}}</version>
        </dependency>

        <!-- Apache HttpClient 5 (synchronous outbound CALL -> REST routing) -->
        <dependency>
            <groupId>org.apache.httpcomponents.client5</groupId>
            <artifactId>httpclient5</artifactId>
            <version>${{httpclient5.version}}</version>
        </dependency>

        <!-- Gson at compile scope (used by JdbcStubExecutor for JSON bodies) -->
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
        </dependency>

        <!-- Mockito (test scope) -->
        <dependency>
            <groupId>org.mockito</groupId>
            <artifactId>mockito-core</artifactId>
            <version>${{mockito.version}}</version>
            <scope>test</scope>
        </dependency>
        <dependency>
            <groupId>org.mockito</groupId>
            <artifactId>mockito-junit-jupiter</artifactId>
            <version>${{mockito.version}}</version>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <!-- Surefire for running JUnit 5 tests -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-surefire-plugin</artifactId>
                <version>3.2.5</version>
            </plugin>

            <!-- Compiler plugin (explicit Java 17) -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-compiler-plugin</artifactId>
                <version>3.12.1</version>
                <configuration>
                    <source>17</source>
                    <target>17</target>
                </configuration>
            </plugin>

            <!-- Shade plugin for runnable fat JAR -->
            <plugin>
                <groupId>org.apache.maven.plugins</groupId>
                <artifactId>maven-shade-plugin</artifactId>
                <version>3.5.2</version>
                <executions>
                    <execution>
                        <phase>package</phase>
                        <goals>
                            <goal>shade</goal>
                        </goals>
                        <configuration>
                            <transformers>
                                <transformer implementation="org.apache.maven.plugins.shade.resource.ManifestResourceTransformer">
                                    <mainClass>{main_class}</mainClass>
                                </transformer>
                            </transformers>
                        </configuration>
                    </execution>
                </executions>
            </plugin>
        </plugins>
    </build>
</project>
"""
