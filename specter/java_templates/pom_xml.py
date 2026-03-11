"""Maven pom.xml template for generated Specter Java projects.

The template uses Python ``str.format`` placeholders:
- ``{group_id}``     -- Maven group ID (e.g. ``com.example``)
- ``{artifact_id}``  -- Maven artifact ID (e.g. ``cobol-program``)
- ``{program_name}`` -- Human-readable program name for ``<name>``
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

        <!-- Gson (test scope - for loading test-store JSONL) -->
        <dependency>
            <groupId>com.google.code.gson</groupId>
            <artifactId>gson</artifactId>
            <version>2.10.1</version>
            <scope>test</scope>
        </dependency>

        <!-- Lanterna terminal UI -->
        <dependency>
            <groupId>com.googlecode.lanterna</groupId>
            <artifactId>lanterna</artifactId>
            <version>${{lanterna.version}}</version>
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
        </plugins>
    </build>
</project>
"""
