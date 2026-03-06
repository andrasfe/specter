       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST16.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(4) VALUE 12.
       01 WS-B           PIC 9(4) VALUE 5.
       01 WS-C           PIC 9(8) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           MULTIPLY WS-A BY WS-B
           DISPLAY 'MUL-BY:' WS-B
           DIVIDE 60 INTO WS-B
           DISPLAY 'DIV-INTO:' WS-B
           DIVIDE WS-A BY 5 GIVING WS-C
           DISPLAY 'DIV-GIVING:' WS-C
           STOP RUN.
