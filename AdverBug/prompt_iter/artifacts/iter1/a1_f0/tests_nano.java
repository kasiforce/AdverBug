package tools.jackson.databind.deser.jdk;

import org.junit.Test;
import static org.junit.Assert.*;

import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.cfg.EnumFeature;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.core.JacksonException;
import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonEnumDefaultValue;

public class DeserializeTests {

    public enum DelegatingEnum {
        A, B;

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static DelegatingEnum fromValue(String s) {
            return DelegatingEnum.valueOf(s);
        }
    }

    public enum ZeroArgEnum {
        ONE, TWO;

        @JsonCreator(mode = JsonCreator.Mode.DELEGATING)
        public static ZeroArgEnum create() {
            return ONE;
        }
    }

    public enum UnknownEnumWithDefault {
        A, B, @JsonEnumDefaultValue DEFAULT;
    }

    @Test
    public void testDelegatingEnumBasic() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        DelegatingEnum v = mapper.readValue("\"A\"", DelegatingEnum.class);
        assertEquals(DelegatingEnum.A, v);
    }

    @Test
    public void testZeroArgFactoryEnum() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        ZeroArgEnum v = mapper.readValue("{}", ZeroArgEnum.class);
        assertEquals(ZeroArgEnum.ONE, v);
    }

    @Test
    public void testUnknownEnumWithDefaultValue() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()

                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE)

                .build();
        UnknownEnumWithDefault v = mapper.readValue("\"C\"", UnknownEnumWithDefault.class);
        assertEquals(UnknownEnumWithDefault.DEFAULT, v);
    }

    @Test
    public void testUnknownEnumAsNull() throws Exception {
        ObjectMapper mapper = JsonMapper.builder()

                .enable(EnumFeature.READ_UNKNOWN_ENUM_VALUES_AS_NULL)

                .build();
        UnknownEnumWithDefault v = mapper.readValue("\"C\"", UnknownEnumWithDefault.class);
        assertNull(v);
    }

    @Test
    public void testInvalidInputForDelegatingEnum() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        try {
            mapper.readValue("{\"x\":1}", DelegatingEnum.class);
            fail("Expected JacksonException");
        } catch (JacksonException e) {
            // expected
        }
    }
}