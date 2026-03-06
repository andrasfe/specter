       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST55.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N           PIC 9(4) VALUE 1.
       01 WS-FACT        PIC 9(8) VALUE 1.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM UNTIL WS-N > 5
               MULTIPLY WS-N BY WS-FACT
               ADD 1 TO WS-N
           END-PERFORM
           DISPLAY 'FACT5:' WS-FACT
           STOP RUN.
