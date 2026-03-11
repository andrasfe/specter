       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCTLOOK.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT ACCOUNT-FILE ASSIGN TO 'ACCTFILE'
               ORGANIZATION IS INDEXED
               ACCESS IS RANDOM
               RECORD KEY IS ACCT-ID
               FILE STATUS IS WS-FILE-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD ACCOUNT-FILE.
       01 ACCOUNT-RECORD.
          05 ACCT-ID         PIC X(10).
          05 ACCT-NAME       PIC X(30).
          05 ACCT-BALANCE    PIC S9(9)V99.
       WORKING-STORAGE SECTION.
       01 WS-FILE-STATUS     PIC XX VALUE '00'.
       01 WS-ACCT-FOUND      PIC X VALUE 'N'.
       01 WS-RETURN-CODE     PIC S9(4) VALUE 0.
       01 WS-DATE-RESULT.
          05 WS-YEAR         PIC 9(4).
          05 WS-MONTH        PIC 9(2).
          05 WS-DAY          PIC 9(2).
       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT ACCOUNT-FILE
           IF WS-FILE-STATUS NOT = '00'
               DISPLAY 'FILE OPEN ERROR: ' WS-FILE-STATUS
               STOP RUN
           END-IF
           MOVE '1234567890' TO ACCT-ID
           PERFORM 1000-READ-ACCOUNT
           IF WS-ACCT-FOUND = 'Y'
               DISPLAY 'ACCOUNT: ' ACCT-NAME
               DISPLAY 'BALANCE: ' ACCT-BALANCE
               PERFORM 2000-GET-DATE
           ELSE
               DISPLAY 'ACCOUNT NOT FOUND'
           END-IF
           CLOSE ACCOUNT-FILE
           STOP RUN.
       1000-READ-ACCOUNT.
           READ ACCOUNT-FILE INTO ACCOUNT-RECORD
               INVALID KEY
                  MOVE 'N' TO WS-ACCT-FOUND
           END-READ
           IF WS-FILE-STATUS = '00'
               MOVE 'Y' TO WS-ACCT-FOUND
           ELSE
               MOVE 'N' TO WS-ACCT-FOUND
           END-IF.
       2000-GET-DATE.
           CALL 'DATEUTIL' USING WS-DATE-RESULT
           IF RETURN-CODE = 0
               DISPLAY 'DATE: ' WS-YEAR '/' WS-MONTH '/' WS-DAY
           ELSE
               DISPLAY 'DATE LOOKUP FAILED'
           END-IF.
