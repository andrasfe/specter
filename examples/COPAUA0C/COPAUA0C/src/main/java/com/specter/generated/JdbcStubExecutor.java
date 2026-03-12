package com.specter.generated;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * {@link StubExecutor} implementation backed by real JDBC and JMS connections.
 *
 * <p>CICS READ / DLI GU / ISRT / REPL operations are translated to SQL
 * statements via JDBC.  MQ CALL operations are translated to JMS
 * operations.  Other operations fall back to the default stub behaviour.
 *
 * <p>Implements {@link AutoCloseable} so it can be used in
 * try-with-resources blocks.
 */
public class JdbcStubExecutor implements StubExecutor, AutoCloseable {

    private final javax.sql.DataSource dataSource;
    private Connection conn;

    /* JMS fields -- nullable (JMS is optional at runtime). */
    private Object jmsFactory;   // jakarta.jms.ConnectionFactory
    private Object jmsConn;      // jakarta.jms.Connection
    private Object jmsSession;   // jakarta.jms.Session
    private Object jmsConsumer;  // jakarta.jms.MessageConsumer
    private Object jmsProducer;  // jakarta.jms.MessageProducer

    /**
     * Create a JdbcStubExecutor.
     *
     * @param dataSource JDBC DataSource for database operations
     * @param jmsFactory JMS ConnectionFactory (may be {@code null})
     */
    public JdbcStubExecutor(javax.sql.DataSource dataSource, Object jmsFactory) {
        this.dataSource = dataSource;
        this.jmsFactory = jmsFactory;
    }

    private Connection getConnection() throws SQLException {
        if (conn == null || conn.isClosed()) {
            conn = dataSource.getConnection();
        }
        return conn;
    }

    /**
     * Close all held connections (JDBC and JMS).
     */
    @Override
    public void close() {
        try {
            if (conn != null && !conn.isClosed()) {
                conn.close();
            }
        } catch (SQLException ignored) {
        }
        // Close JMS resources via reflection (optional dependency)
        closeJms();
    }

    private void closeJms() {
        try {
            if (jmsSession != null) {
                jmsSession.getClass().getMethod("close").invoke(jmsSession);
            }
            if (jmsConn != null) {
                jmsConn.getClass().getMethod("close").invoke(jmsConn);
            }
        } catch (Exception ignored) {
        }
        jmsSession = null;
        jmsConn = null;
        jmsConsumer = null;
        jmsProducer = null;
    }

    // -------------------------------------------------------------------
    // Stub outcome support (delegates to DefaultStubExecutor logic)
    // -------------------------------------------------------------------

    @Override
    public List<Object[]> applyStubOutcome(ProgramState state, String key) {
        List<Object[]> applied = null;
        List<List<Object[]>> queue = state.stubOutcomes.get(key);
        if (queue != null && !queue.isEmpty()) {
            applied = queue.remove(0);
        } else {
            List<Object[]> defaults = state.stubDefaults.get(key);
            if (defaults != null && !defaults.isEmpty()) {
                applied = new java.util.ArrayList<>(defaults);
            }
        }
        if (applied != null) {
            for (Object[] pair : applied) {
                state.put(pair[0].toString(), pair[1]);
            }
        }
        state.stubLog.add(new Object[]{key, applied});
        return applied;
    }

    @Override
    public void dummyCall(ProgramState state, String programName) {
        String opKey = "CALL:" + programName;
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", programName);
        state.calls.add(entry);
        applyStubOutcome(state, opKey);
    }

    @Override
    public void dummyExec(ProgramState state, String kind, String rawText) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("kind", kind);
        entry.put("text", rawText);
        state.execs.add(entry);
        applyStubOutcome(state, kind);
    }

    // -------------------------------------------------------------------
    // CICS typed operations
    // -------------------------------------------------------------------

    @Override
    public void cicsRead(ProgramState state, String dataset, String ridfld, String intoRecord, String respVar, String resp2Var) {
        try {
            String tableName = dataset.replace("-", "_");
            String keyCol = ridfld.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "SELECT * FROM " + tableName + " WHERE " + keyCol + " = ?");
            ps.setString(1, state.get(ridfld).toString());
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {
                ResultSetMetaData meta = rs.getMetaData();
                for (int i = 1; i <= meta.getColumnCount(); i++) {
                    String colName = meta.getColumnName(i).replace("_", "-");
                    state.put(colName, rs.getObject(i));
                }
                if (respVar != null) state.put(respVar, 0);  // NORMAL
            } else {
                if (respVar != null) state.put(respVar, 13);  // NOTFND
            }
            rs.close();
            ps.close();
        } catch (SQLException e) {
            if (respVar != null) state.put(respVar, 12);  // ERROR
            throw new RuntimeException(e);
        }
    }

    @Override
    public void cicsReturn(ProgramState state) {
        throw new GobackSignal();
    }

    @Override
    public void cicsRetrieve(ProgramState state, String intoVar) {
        if (jmsConsumer == null) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("kind", "CICS");
            entry.put("text", "RETRIEVE INTO(" + (intoVar != null ? intoVar : "") + ")");
            state.execs.add(entry);
            applyStubOutcome(state, "CICS");
            return;
        }
        try {
            java.lang.reflect.Method recv = jmsConsumer.getClass().getMethod("receive", long.class);
            Object msg = recv.invoke(jmsConsumer, 5000L);
            if (msg != null && intoVar != null) {
                java.lang.reflect.Method getText = msg.getClass().getMethod("getText");
                state.put(intoVar, getText.invoke(msg));
            }
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void cicsSyncpoint(ProgramState state) {
        try {
            getConnection().commit();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void cicsAsktime(ProgramState state, String abstimeVar) {
        if (abstimeVar != null) {
            state.put(abstimeVar, Instant.now().toEpochMilli());
        }
    }

    @Override
    public void cicsFormattime(ProgramState state, String abstimeVar, String dateVar, String timeVar, String msVar) {
        long abstime = 0;
        if (abstimeVar != null) {
            Object v = state.get(abstimeVar);
            if (v instanceof Number) abstime = ((Number) v).longValue();
        }
        LocalDateTime dt = LocalDateTime.ofInstant(Instant.ofEpochMilli(abstime), ZoneId.systemDefault());
        if (dateVar != null) {
            state.put(dateVar, dt.format(DateTimeFormatter.ofPattern("yyDDD")));
        }
        if (timeVar != null) {
            state.put(timeVar, dt.format(DateTimeFormatter.ofPattern("HHmmss")));
        }
        if (msVar != null) {
            state.put(msVar, String.valueOf(abstime % 1000));
        }
    }

    @Override
    public void cicsWriteqTd(ProgramState state, String queue, String fromRecord) {
        if (jmsProducer == null) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("kind", "CICS");
            entry.put("text", "WRITEQ TD QUEUE(" + (queue != null ? queue : "") + ")");
            state.execs.add(entry);
            applyStubOutcome(state, "CICS");
            return;
        }
        try {
            java.lang.reflect.Method createText = jmsSession.getClass()
                .getMethod("createTextMessage", String.class);
            Object msg = createText.invoke(jmsSession,
                fromRecord != null ? state.get(fromRecord).toString() : "");
            java.lang.reflect.Method send = jmsProducer.getClass()
                .getMethod("send", Class.forName("jakarta.jms.Message"));
            send.invoke(jmsProducer, msg);
        } catch (Exception e) {
            throw new RuntimeException(e);
        }
    }

    // -------------------------------------------------------------------
    // DLI / IMS typed operations
    // -------------------------------------------------------------------

    @Override
    public void dliSchedulePsb(ProgramState state, String psbName) {
        try {
            conn = dataSource.getConnection();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void dliTerminate(ProgramState state) {
        try {
            if (conn != null && !conn.isClosed()) {
                conn.close();
            }
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void dliGetUnique(ProgramState state, String segment, String intoRecord, String whereCol, String whereVar) {
        try {
            String tableName = segment.replace("-", "_");
            String keyCol = whereCol != null ? whereCol.replace("-", "_") : "ID";
            PreparedStatement ps = getConnection().prepareStatement(
                "SELECT * FROM " + tableName + " WHERE " + keyCol + " = ?");
            ps.setString(1, whereVar != null ? state.get(whereVar).toString() : "");
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {
                ResultSetMetaData meta = rs.getMetaData();
                for (int i = 1; i <= meta.getColumnCount(); i++) {
                    String colName = meta.getColumnName(i).replace("_", "-");
                    state.put(colName, rs.getObject(i));
                }
            }
            rs.close();
            ps.close();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void dliInsert(ProgramState state, String segment, String fromRecord) {
        try {
            String tableName = segment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "INSERT INTO " + tableName + " DEFAULT VALUES");
            ps.executeUpdate();
            ps.close();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void dliInsertChild(ProgramState state, String parentSegment, String parentWhereCol, String parentWhereVar, String childSegment, String fromRecord) {
        try {
            String tableName = childSegment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "INSERT INTO " + tableName + " DEFAULT VALUES");
            ps.executeUpdate();
            ps.close();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    @Override
    public void dliReplace(ProgramState state, String segment, String fromRecord) {
        try {
            String tableName = segment.replace("-", "_");
            PreparedStatement ps = getConnection().prepareStatement(
                "UPDATE " + tableName + " SET dummy = 1 WHERE 1=0");
            ps.executeUpdate();
            ps.close();
        } catch (SQLException e) {
            throw new RuntimeException(e);
        }
    }

    // -------------------------------------------------------------------
    // MQ typed operations
    // -------------------------------------------------------------------

    @Override
    public void mqOpen(ProgramState state, String queueNameVar) {
        if (jmsFactory == null) {
            dummyCall(state, "MQOPEN");
            return;
        }
        try {
            java.lang.reflect.Method createConn = jmsFactory.getClass()
                .getMethod("createConnection", String.class, String.class);
            jmsConn = createConn.invoke(jmsFactory,
                AppConfig.getJmsUser(), AppConfig.getJmsPassword());
            java.lang.reflect.Method createSess = jmsConn.getClass()
                .getMethod("createSession", boolean.class, int.class);
            jmsSession = createSess.invoke(jmsConn, false, 1);
            String qName = queueNameVar != null ? state.get(queueNameVar).toString().trim() : "";
            if (qName.isEmpty()) qName = "SPECTER.DEFAULT";
            java.lang.reflect.Method createQueue = jmsSession.getClass()
                .getMethod("createQueue", String.class);
            Object queue = createQueue.invoke(jmsSession, qName);
            java.lang.reflect.Method createConsumer = jmsSession.getClass()
                .getMethod("createConsumer", Class.forName("jakarta.jms.Destination"));
            jmsConsumer = createConsumer.invoke(jmsSession, queue);
            java.lang.reflect.Method createProducer = jmsSession.getClass()
                .getMethod("createProducer", Class.forName("jakarta.jms.Destination"));
            jmsProducer = createProducer.invoke(jmsSession, queue);
            state.put("WS-COMPLETION-CODE", 0);  // MQCC_OK
        } catch (Exception e) {
            System.err.println("MQ OPEN failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);  // MQCC_FAILED
            state.put("WS-REASON-CODE", 2085);   // MQRC_UNKNOWN_OBJECT_NAME
        }
    }

    @Override
    public void mqGet(ProgramState state, String bufferVar, String datalenVar, String waitIntervalVar) {
        if (jmsConsumer == null) {
            dummyCall(state, "MQGET");
            return;
        }
        try {
            long timeout = 5000;
            if (waitIntervalVar != null) {
                Object wv = state.get(waitIntervalVar);
                if (wv instanceof Number) timeout = ((Number) wv).longValue();
            }
            java.lang.reflect.Method recv = jmsConsumer.getClass()
                .getMethod("receive", long.class);
            Object msg = recv.invoke(jmsConsumer, timeout);
            if (msg != null && bufferVar != null) {
                java.lang.reflect.Method getText = msg.getClass().getMethod("getText");
                String text = (String) getText.invoke(msg);
                state.put(bufferVar, text);
                if (datalenVar != null) state.put(datalenVar, text.length());
                state.put("WS-COMPLETION-CODE", 0);
            } else {
                state.put("WS-COMPLETION-CODE", 2);
                state.put("WS-REASON-CODE", 2033);   // MQRC_NO_MSG_AVAILABLE
            }
        } catch (Exception e) {
            System.err.println("MQ GET failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);
            state.put("WS-REASON-CODE", 2033);
        }
    }

    @Override
    public void mqPut1(ProgramState state, String replyQueueVar, String bufferVar, String buflenVar) {
        if (jmsProducer == null) {
            dummyCall(state, "MQPUT1");
            return;
        }
        try {
            java.lang.reflect.Method createText = jmsSession.getClass()
                .getMethod("createTextMessage", String.class);
            String body = bufferVar != null ? state.get(bufferVar).toString() : "";
            Object msg = createText.invoke(jmsSession, body);
            java.lang.reflect.Method send = jmsProducer.getClass()
                .getMethod("send", Class.forName("jakarta.jms.Message"));
            send.invoke(jmsProducer, msg);
            state.put("WS-COMPLETION-CODE", 0);
        } catch (Exception e) {
            System.err.println("MQ PUT1 failed: " + e.getMessage());
            state.put("WS-COMPLETION-CODE", 2);
            state.put("WS-REASON-CODE", 2085);
        }
    }

    @Override
    public void mqClose(ProgramState state) {
        closeJms();
        state.put("WS-COMPLETION-CODE", 0);
    }
}
