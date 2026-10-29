import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonSubTypes;
import com.fasterxml.jackson.annotation.JsonTypeInfo;

import tools.jackson.core.JacksonException;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.ObjectMapper;

/**
 * Tests for ExternalTypeHandler.complete(JsonParser, DeserializationContext,
 * PropertyValueBuffer, PropertyBasedCreator), i.e. the creator-based completion
 * of deserialization of beans that use external type ids
 * ({@code JsonTypeInfo.As.EXTERNAL_PROPERTY}). All beans below use
 * {@code @JsonCreator} constructors so that the creator-based complete()
 * path (not the plain bean-based one) is exercised.
 */
public class CompleteTests {

    private final ObjectMapper mapper = new ObjectMapper();

    /*
     **********************************************************
     * Helper types
     **********************************************************
     */

    public static class Pet { }

    public static class Dog extends Pet {
        public String bark;
    }

    public static class Cat extends Pet {
        public String meow;
    }

    /**
     * Bean with a property-based creator where the external-type-id target
     * ("pet") is itself a creator property, and where the type id property
     * ("petType") is not a bean property.
     */
    public static class PetOwnerBean {
        public final String name;
        public final Pet pet;

        @JsonCreator
        public PetOwnerBean(@JsonProperty("name") String name,
                @JsonProperty("pet")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "petType")
                @JsonSubTypes({ @JsonSubTypes.Type(value = Dog.class, name = "dog"),
                        @JsonSubTypes.Type(value = Cat.class, name = "cat") })
                Pet pet) {
            this.name = name;
            this.pet = pet;
        }
    }

    /**
     * Bean whose external-type-id property has a "natural" (String) value type,
     * for which no type id is included for natural values.
     */
    public static class NaturalValueBean {
        public final String name;
        public final String value;

        @JsonCreator
        public NaturalValueBean(@JsonProperty("name") String name,
                @JsonProperty("value")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "valueType")
                String value) {
            this.name = name;
            this.value = value;
        }
    }

    /**
     * Like PetOwnerBean but with {@code defaultImpl} configured, so a missing
     * type id falls back to the default implementation instead of failing.
     */
    public static class DefaultPetOwnerBean {
        public final String name;
        public final Pet pet;

        @JsonCreator
        public DefaultPetOwnerBean(@JsonProperty("name") String name,
                @JsonProperty("pet")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "petType",
                        defaultImpl = Cat.class)
                @JsonSubTypes({ @JsonSubTypes.Type(value = Dog.class, name = "dog"),
                        @JsonSubTypes.Type(value = Cat.class, name = "cat") })
                Pet pet) {
            this.name = name;
            this.pet = pet;
        }
    }

    /**
     * Bean where the external type id property ("petType") is also exposed as
     * a creator property of its own (databind#999).
     */
    public static class TypeIdAsCreatorPropertyBean {
        public final String name;
        public final String petType;
        public final Pet pet;

        @JsonCreator
        public TypeIdAsCreatorPropertyBean(@JsonProperty("name") String name,
                @JsonProperty("petType") String petType,
                @JsonProperty("pet")
                @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                        include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                        property = "petType")
                @JsonSubTypes({ @JsonSubTypes.Type(value = Dog.class, name = "dog"),
                        @JsonSubTypes.Type(value = Cat.class, name = "cat") })
                Pet pet) {
            this.name = name;
            this.petType = petType;
            this.pet = pet;
        }
    }

    /**
     * Bean mixing a creator property ("name") with a non-creator
     * external-type-id property ("pet"); the non-creator property must be
     * assigned after the creator has built the instance.
     */
    public static class MixedBean {
        public final String name;

        @JsonTypeInfo(use = JsonTypeInfo.Id.NAME,
                include = JsonTypeInfo.As.EXTERNAL_PROPERTY,
                property = "petType")
        @JsonSubTypes({ @JsonSubTypes.Type(value = Dog.class, name = "dog"),
                @JsonSubTypes.Type(value = Cat.class, name = "cat") })
        public Pet pet;

        @JsonCreator
        public MixedBean(@JsonProperty("name") String name) {
            this.name = name;
        }
    }

    /*
     **********************************************************
     * Basic functionality
     **********************************************************
     */

    @Test
    public void testTypeIdBeforeValue() throws Exception {
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"petType\":\"dog\",\"pet\":{\"bark\":\"woof\"}}",
                PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNotNull(bean.pet);
        assertTrue(bean.pet instanceof Dog);
        assertEquals("woof", ((Dog) bean.pet).bark);
    }

    @Test
    public void testValueBeforeTypeId() throws Exception {
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"pet\":{\"bark\":\"woof\"},\"petType\":\"dog\"}",
                PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNotNull(bean.pet);
        assertTrue(bean.pet instanceof Dog);
        assertEquals("woof", ((Dog) bean.pet).bark);
    }

    @Test
    public void testExplicitNullValueWithTypeId() throws Exception {
        // Explicit null value matching a present type id binds as null
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"pet\":null,\"petType\":\"dog\"}",
                PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNull(bean.pet);
    }

    @Test
    public void testTypeIdAssignedToCreatorProperty() throws Exception {
        // databind#999: external type id must be assigned to a matching
        // creator property too
        TypeIdAsCreatorPropertyBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"petType\":\"dog\",\"pet\":{\"bark\":\"loud\"}}",
                TypeIdAsCreatorPropertyBean.class);
        assertEquals("Bob", bean.name);
        assertEquals("dog", bean.petType);
        assertNotNull(bean.pet);
        assertTrue(bean.pet instanceof Dog);
        assertEquals("loud", ((Dog) bean.pet).bark);
    }

    @Test
    public void testNonCreatorExternalPropertyAssignedAfterBuild() throws Exception {
        MixedBean bean = mapper.readValue(
                "{\"name\":\"Sue\",\"pet\":{\"bark\":\"soft\"},\"petType\":\"dog\"}",
                MixedBean.class);
        assertEquals("Sue", bean.name);
        assertNotNull(bean.pet);
        assertTrue(bean.pet instanceof Dog);
        assertEquals("soft", ((Dog) bean.pet).bark);
    }

    /*
     **********************************************************
     * Boundary conditions and edge cases
     **********************************************************
     */

    @Test
    public void testMissingValueAndTypeIdLeftNull() throws Exception {
        // Missing both value and type id: property simply left null
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\"}", PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNull(bean.pet);
    }

    @Test
    public void testExplicitNullValueWithoutTypeIdAccepted() throws Exception {
        // Explicit null value without any type id must be accepted
        // (no exception), leaving the property as null
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"pet\":null}", PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNull(bean.pet);
    }

    @Test
    public void testNaturalScalarValueWithoutTypeId() throws Exception {
        // databind#3786: natural scalar values (String) with no type id
        // are deserialized directly instead of failing
        NaturalValueBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"value\":\"plain\"}", NaturalValueBean.class);
        assertEquals("Bob", bean.name);
        assertEquals("plain", bean.value);
    }

    @Test
    public void testPresentTypeIdWithMissingValue() throws Exception {
        // databind#3533: present type id but absent value deserializes as null
        PetOwnerBean bean = mapper.readValue(
                "{\"name\":\"Bob\",\"petType\":\"dog\"}", PetOwnerBean.class);
        assertEquals("Bob", bean.name);
        assertNull(bean.pet);
    }

    /*
     **********************************************************
     * Invalid inputs and error handling
     **********************************************************
     */

    @Test
    public void testMissingTypeIdWithPresentObjectValueFails() throws Exception {
        // Value present but no type id and no defaultImpl: must fail with
        // "missing external type id" instead of silently dropping the value
        try {
            mapper.readValue(
                    "{\"name\":\"Bob\",\"pet\":{\"bark\":\"woof\"}}",
                    PetOwnerBean.class);
            fail("Expected an exception for missing external type id");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testDefaultImplUsedWhenTypeIdMissing() throws Exception {
        // databind#94: with defaultImpl, a missing type id falls back to the
        // default implementation; an explicit type id still takes precedence
        DefaultPetOwnerBean withDefault = mapper.readValue(
                "{\"name\":\"Bob\",\"pet\":{\"meow\":\"soft\"}}",
                DefaultPetOwnerBean.class);
        assertEquals("Bob", withDefault.name);
        assertNotNull(withDefault.pet);
        assertTrue(withDefault.pet instanceof Cat);
        assertEquals("soft", ((Cat) withDefault.pet).meow);

        DefaultPetOwnerBean withId = mapper.readValue(
                "{\"name\":\"Bob\",\"petType\":\"dog\",\"pet\":{\"bark\":\"loud\"}}",
                DefaultPetOwnerBean.class);
        assertNotNull(withId.pet);
        assertTrue(withId.pet instanceof Dog);
        assertEquals("loud", ((Dog) withId.pet).bark);
    }

    @Test
    public void testFailOnMissingExternalTypeIdPropertyEnabled() throws Exception {
        // With FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY, a present type id
        // without a matching value must trigger a failure
        try {
            mapper.readerFor(PetOwnerBean.class)
                    .with(DeserializationFeature.FAIL_ON_MISSING_EXTERNAL_TYPE_ID_PROPERTY)
                    .readValue("{\"name\":\"Bob\",\"petType\":\"dog\"}");
            fail("Expected an exception when missing external type id value is not allowed");
        } catch (JacksonException e) {
            // expected
        }
    }

    @Test
    public void testUnknownTypeIdFails() throws Exception {
        try {
            mapper.readValue(
                    "{\"name\":\"Bob\",\"petType\":\"dinosaur\",\"pet\":{\"bark\":\"loud\"}}",
                    PetOwnerBean.class);
            fail("Expected an exception for unknown external type id");
        } catch (JacksonException e) {
            // expected
        }
    }
}