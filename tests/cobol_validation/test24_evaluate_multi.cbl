       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST24.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A           PIC 9(2) VALUE 3.
       01 WS-B           PIC X(1) VALUE 'Y'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           EVALUATE TRUE
               WHEN WS-A = 1
                   DISPLAY 'A-IS-1'
               WHEN WS-A = 2
                   DISPLAY 'A-IS-2'
               WHEN WS-A = 3
                   DISPLAY 'A-IS-3'
               WHEN OTHER
                   DISPLAY 'A-OTHER'
           END-EVALUATE
           EVALUATE WS-B
               WHEN 'Y'
                   DISPLAY 'B-IS-Y'
               WHEN 'N'
                   DISPLAY 'B-IS-N'
           END-EVALUATE
           STOP RUN.
