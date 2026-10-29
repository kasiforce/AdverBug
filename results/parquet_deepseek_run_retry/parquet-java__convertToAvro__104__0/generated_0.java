/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

package org.apache.parquet.cli.json;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.BinaryNode;
import com.fasterxml.jackson.databind.node.FloatNode;
import com.fasterxml.jackson.databind.node.NullNode;
import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.avro.AvroRuntimeException;
import org.apache.avro.Schema;
import org.apache.avro.SchemaBuilder;
import org.apache.avro.generic.GenericData;
import org.apache.avro.generic.GenericRecord;
import org.apache.parquet.cli.util.RecordException;
import org.junit.jupiter.api.Test;

/**
 * Tests for {@link AvroJson#convertToAvro(GenericData, JsonNode, Schema)}.
 *
 * <p>These tests only use the public contract of the converter: the JSON datum, the Avro schema and the
 * {@link GenericData} model passed in, plus the value (or exception) that comes back out.
 */
class AvroJsonConvertToAvroTests {

  private final GenericData model = new GenericData();

  private static JsonNode json(String text) {
    return AvroJson.parse(text);
  }

  private static Schema schema(String text) {
    return new Schema.Parser().parse(text);
  }

  private Object convert(JsonNode datum, Schema schema) {
    return AvroJson.convertToAvro(model, datum, schema);
  }

  // ------------------------------------------------------------------
  // null datum handling
  // ------------------------------------------------------------------

  @Test
  void nullDatumReturnsNullForAnySchema() {
    assertThat(convert(null, Schema.create(Schema.Type.INT))).isNull();
    assertThat(convert(null, Schema.create(Schema.Type.STRING))).isNull();
    assertThat(convert(null, Schema.create(Schema.Type.NULL))).isNull();
    assertThat(convert(
            null,
            SchemaBuilder.record("R")
                .fields()
                .name("a")
                .type()
                .intType()
                .noDefault()
                .endRecord()))
        .isNull();
  }

  @Test
  void nullSchemaTypeAlwaysReturnsNull() {
    Schema nullSchema = Schema.create(Schema.Type.NULL);
    assertThat(convert(json("null"), nullSchema)).isNull();
    assertThat(convert(NullNode.getInstance(), nullSchema)).isNull();
  }

  // ------------------------------------------------------------------
  // RECORD
  // ------------------------------------------------------------------

  @Test
  void recordIsConvertedFieldByField() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("flag")
        .type()
        .booleanType()
        .noDefault()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .name("label")
        .type()
        .stringType()
        .noDefault()
        .endRecord();

    Object result = convert(json("{\"flag\": true, \"count\": 7, \"label\": \"hi\"}"), recordSchema);

    assertThat(result).isInstanceOf(GenericRecord.class);
    GenericRecord record = (GenericRecord) result;
    assertThat(record.getSchema()).isEqualTo(recordSchema);
    assertThat(record.get("flag")).isEqualTo(Boolean.TRUE);
    assertThat(record.get("count")).isEqualTo(7);
    assertThat(record.get("label")).isEqualTo("hi");
  }

  @Test
  void recordUsesFieldDefaultWhenJsonFieldIsAbsent() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .intDefault(42)
        .endRecord();

    GenericRecord record = (GenericRecord) convert(json("{}"), recordSchema);

    assertThat(record.get("count")).isEqualTo(42);
  }

  @Test
  void recordUsesNullForAbsentNullableField() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .optional()
        .intType()
        .endRecord();

    GenericRecord record = (GenericRecord) convert(json("{}"), recordSchema);

    assertThat(record.get("count")).isNull();
  }

  @Test
  void recordIgnoresFieldsThatAreNotInTheSchema() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();

    GenericRecord record = (GenericRecord) convert(json("{\"count\": 3, \"extra\": \"ignored\"}"), recordSchema);

    assertThat(record.get("count")).isEqualTo(3);
    assertThat(record.getSchema().getFields()).hasSize(1);
  }

  @Test
  void recordWithNoFieldsIsEmpty() {
    Schema recordSchema = SchemaBuilder.record("Empty").fields().endRecord();

    GenericRecord record = (GenericRecord) convert(json("{}"), recordSchema);

    assertThat(record.getSchema().getFields()).isEmpty();
  }

  @Test
  void nestedRecordsAreConvertedRecursively() {
    Schema inner = SchemaBuilder.record("Inner")
        .fields()
        .name("value")
        .type()
        .longType()
        .noDefault()
        .endRecord();
    Schema outer = SchemaBuilder.record("Outer")
        .fields()
        .name("inner")
        .type(inner)
        .noDefault()
        .endRecord();

    GenericRecord record = (GenericRecord) convert(json("{\"inner\": {\"value\": 12}}"), outer);

    assertThat(record.get("inner")).isInstanceOf(GenericRecord.class);
    assertThat(((GenericRecord) record.get("inner")).get("value")).isEqualTo(12L);
  }

  @Test
  void recordFailsForNonObjectDatum() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();

    assertThatThrownBy(() -> convert(json("[1, 2]"), recordSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert non-object to record");
  }

  @Test
  void recordFailsWhenAFieldCannotBeConverted() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();

    assertThatThrownBy(() -> convert(json("{\"count\": \"not-a-number\"}"), recordSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert field count")
        .hasCauseInstanceOf(RecordException.class)
        .cause()
        .hasMessageContaining("Cannot convert to int");
  }

  @Test
  void recordFailsWhenRequiredFieldIsMissingAndHasNoDefault() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();

    assertThatThrownBy(() -> convert(json("{}"), recordSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Field count: cannot make")
        .hasMessageContaining("'null'")
        .hasCauseInstanceOf(AvroRuntimeException.class);
  }

  @Test
  void recordFailsWhenNullableFieldIsExplicitlyNullButNotNullable() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();

    assertThatThrownBy(() -> convert(json("{\"count\": null}"), recordSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert field count")
        .cause()
        .hasMessageContaining("Cannot convert to int");
  }

  @Test
  void nestedRecordFailureReportsTheFailingOuterField() {
    Schema inner = SchemaBuilder.record("Inner")
        .fields()
        .name("value")
        .type()
        .intType()
        .noDefault()
        .endRecord();
    Schema outer = SchemaBuilder.record("Outer")
        .fields()
        .name("inner")
        .type(inner)
        .noDefault()
        .endRecord();

    assertThatThrownBy(() -> convert(json("{\"inner\": {\"value\": \"oops\"}}"), outer))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert field inner")
        .cause()
        .hasMessageContaining("Cannot convert field value");
  }

  // ------------------------------------------------------------------
  // MAP
  // ------------------------------------------------------------------

  @Test
  void mapIsConvertedPreservingJsonPropertyOrder() {
    Schema mapSchema = SchemaBuilder.map().values().intType();
    JsonNode datum = json("{\"second\": 2, \"first\": 1, \"third\": 3}");

    Object result = convert(datum, mapSchema);

    assertThat(result).isInstanceOf(Map.class);
    Map<String, Object> map = (Map<String, Object>) result;
    assertThat(new ArrayList<>(map.keySet())).containsExactly("second", "first", "third");
    assertThat(map).containsEntry("second", 2).containsEntry("first", 1).containsEntry("third", 3);
  }

  @Test
  void emptyJsonObjectBecomesEmptyMap() {
    Object result = convert(json("{}"), SchemaBuilder.map().values().stringType());

    assertThat(result).isInstanceOf(Map.class);
    assertThat((Map<String, Object>) result).isEmpty();
  }

  @Test
  void mapValuesAreConvertedUsingTheValueSchema() {
    Schema valueRecord = SchemaBuilder.record("V")
        .fields()
        .name("n")
        .type()
        .intType()
        .noDefault()
        .endRecord();
    Schema mapSchema = SchemaBuilder.map().values(valueRecord);

    Map<String, Object> map = (Map<String, Object>) convert(json("{\"k\": {\"n\": 5}}"), mapSchema);

    assertThat(map).containsOnlyKeys("k");
    Object value = map.get("k");
    assertThat(value).isInstanceOf(GenericRecord.class);
    assertThat(((GenericRecord) value).get("n")).isEqualTo(5);
  }

  @Test
  void mapFailsForNonObjectDatum() {
    assertThatThrownBy(() ->
            convert(json("[\"a\"]"), SchemaBuilder.map().values().stringType()))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert non-object to map");
  }

  @Test
  void mapFailsWhenAValueCannotBeConverted() {
    assertThatThrownBy(() -> convert(
            json("{\"k\": \"x\"}"), SchemaBuilder.map().values().intType()))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to int");
  }

  // ------------------------------------------------------------------
  // ARRAY
  // ------------------------------------------------------------------

  @Test
  void arrayIsConvertedPreservingOrder() {
    Schema arraySchema = SchemaBuilder.array().items().longType();

    Object result = convert(json("[3, 2, 1]"), arraySchema);

    assertThat(result).isInstanceOf(List.class);
    assertThat((List<Object>) result).containsExactly(3L, 2L, 1L);
  }

  @Test
  void emptyJsonArrayBecomesEmptyList() {
    Object result = convert(json("[]"), SchemaBuilder.array().items().stringType());

    assertThat(result).isInstanceOf(List.class);
    assertThat((List<Object>) result).isEmpty();
  }

  @Test
  void arrayOfRecordsIsConvertedElementWise() {
    Schema elementSchema = SchemaBuilder.record("E")
        .fields()
        .name("n")
        .type()
        .intType()
        .noDefault()
        .endRecord();
    Schema arraySchema = SchemaBuilder.array().items(elementSchema);

    List<Object> list = (List<Object>) convert(json("[{\"n\": 1}, {\"n\": 2}]"), arraySchema);

    assertThat(list).hasSize(2);
    assertThat(((GenericRecord) list.get(0)).get("n")).isEqualTo(1);
    assertThat(((GenericRecord) list.get(1)).get("n")).isEqualTo(2);
  }

  @Test
  void arrayFailsForNonArrayDatum() {
    assertThatThrownBy(() -> convert(
            json("{\"a\": 1}"), SchemaBuilder.array().items().intType()))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to array");
  }

  @Test
  void arrayFailsWhenAnElementCannotBeConverted() {
    assertThatThrownBy(() ->
            convert(json("[true]"), SchemaBuilder.array().items().intType()))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to int");
  }

  // ------------------------------------------------------------------
  // UNION
  // ------------------------------------------------------------------

  @Test
  void nullableUnionConvertsNullToNull() {
    Schema union = SchemaBuilder.unionOf().nullType().and().intType().endUnion();

    assertThat(convert(json("null"), union)).isNull();
    assertThat(convert(NullNode.getInstance(), union)).isNull();
  }

  @Test
  void unionSelectsIntForIntegerDatum() {
    Schema union = SchemaBuilder.unionOf().nullType().and().intType().endUnion();

    Object result = convert(json("42"), union);

    assertThat(result).isInstanceOf(Integer.class).isEqualTo(42);
  }

  @Test
  void unionWidensIntegerDatumToLongWhenIntIsNotAvailable() {
    Schema union = SchemaBuilder.unionOf().nullType().and().longType().endUnion();

    Object result = convert(json("42"), union);

    assertThat(result).isInstanceOf(Long.class).isEqualTo(42L);
  }

  @Test
  void unionSelectsStringForTextualDatum() {
    Schema union = SchemaBuilder.unionOf().nullType().and().stringType().endUnion();

    assertThat(convert(json("\"text\""), union)).isEqualTo("text");
  }

  @Test
  void unionSelectsBooleanForBooleanDatum() {
    Schema union = SchemaBuilder.unionOf().nullType().and().booleanType().endUnion();

    assertThat(convert(json("true"), union)).isEqualTo(Boolean.TRUE);
  }

  @Test
  void unionSelectsTheFirstMatchingRecord() {
    Schema union = schema("[\"null\","
        + "{\"type\": \"record\", \"name\": \"A\", \"fields\": [{\"name\": \"a\", \"type\": \"int\"}]},"
        + "{\"type\": \"record\", \"name\": \"B\", \"fields\": [{\"name\": \"b\", \"type\": \"string\"}]}]");

    GenericRecord first = (GenericRecord) convert(json("{\"a\": 1, \"b\": \"x\"}"), union);
    GenericRecord second = (GenericRecord) convert(json("{\"b\": \"x\"}"), union);

    assertThat(first.getSchema().getName()).isEqualTo("A");
    assertThat(first.get("a")).isEqualTo(1);
    assertThat(second.getSchema().getName()).isEqualTo("B");
    assertThat(second.get("b")).isEqualTo("x");
  }

  @Test
  void unionSelectsMapOrArrayBasedOnTheDatumShape() {
    Schema union = schema(
        "[\"null\", {\"type\": \"array\", \"items\": \"int\"}," + " {\"type\": \"map\", \"values\": \"int\"}]");

    assertThat((List<Object>) convert(json("[1, 2]"), union)).containsExactly(1, 2);
    assertThat((Map<String, Object>) convert(json("{\"k\": 1}"), union)).containsEntry("k", 1);
  }

  @Test
  void unionFailsWhenNoMemberMatches() {
    Schema union = SchemaBuilder.unionOf().nullType().and().stringType().endUnion();

    assertThatThrownBy(() -> convert(json("42"), union))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot resolve union");
  }

  @Test
  void unionFailsWhenDatumDoesNotMatchAnyNonPrimitiveMember() {
    Schema union = schema("[\"string\", \"bytes\"]");

    assertThatThrownBy(() -> convert(json("1"), union))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot resolve union");
  }

  @Test
  void unionOfRecordsFailsWhenNoRecordMatches() {
    Schema union = schema("[\"null\","
        + "{\"type\": \"record\", \"name\": \"A\", \"fields\": [{\"name\": \"a\", \"type\": \"int\"}]}]");

    assertThatThrownBy(() -> convert(json("{\"other\": 1}"), union))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot resolve union");
  }

  // ------------------------------------------------------------------
  // BOOLEAN / FLOAT / DOUBLE / INT / LONG
  // ------------------------------------------------------------------

  @Test
  void booleanIsConverted() {
    Schema booleanSchema = Schema.create(Schema.Type.BOOLEAN);

    assertThat(convert(json("true"), booleanSchema)).isEqualTo(Boolean.TRUE);
    assertThat(convert(json("false"), booleanSchema)).isEqualTo(Boolean.FALSE);
  }

  @Test
  void booleanFailsForNonBooleanDatum() {
    assertThatThrownBy(() -> convert(json("\"true\""), Schema.create(Schema.Type.BOOLEAN)))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to boolean");
  }

  @Test
  void floatAcceptsIntAndFloatNodes() {
    Schema floatSchema = Schema.create(Schema.Type.FLOAT);

    assertThat(convert(json("12"), floatSchema)).isEqualTo(12.0f);
    assertThat(convert(FloatNode.valueOf(1.5f), floatSchema)).isEqualTo(1.5f);
  }

  @Test
  void floatFailsForDoubleAndTextNodes() {
    Schema floatSchema = Schema.create(Schema.Type.FLOAT);

    assertThatThrownBy(() -> convert(json("1.5"), floatSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to float");
    assertThatThrownBy(() -> convert(json("\"1.5\""), floatSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to float");
  }

  @Test
  void doubleAcceptsAllNumericNodes() {
    Schema doubleSchema = Schema.create(Schema.Type.DOUBLE);

    assertThat(convert(json("3"), doubleSchema)).isEqualTo(3.0d);
    assertThat(convert(json("3000000000"), doubleSchema)).isEqualTo(3.0E9d);
    assertThat(convert(FloatNode.valueOf(2.25f), doubleSchema)).isEqualTo(2.25d);
    assertThat(convert(json("2.5"), doubleSchema)).isEqualTo(2.5d);
  }

  @Test
  void doubleFailsForNonNumericDatum() {
    assertThatThrownBy(() -> convert(json("\"2.5\""), Schema.create(Schema.Type.DOUBLE)))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to double");
  }

  @Test
  void intAcceptsIntegerNodesOnly() {
    Schema intSchema = Schema.create(Schema.Type.INT);

    assertThat(convert(json("-7"), intSchema)).isEqualTo(-7);
    assertThat(convert(json("0"), intSchema)).isEqualTo(0);
    assertThat(convert(json(String.valueOf(Integer.MAX_VALUE)), intSchema)).isEqualTo(Integer.MAX_VALUE);

    assertThatThrownBy(() -> convert(json("3000000000"), intSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to int");
    assertThatThrownBy(() -> convert(json("1.0"), intSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to int");
  }

  @Test
  void longAcceptsIntAndLongNodes() {
    Schema longSchema = Schema.create(Schema.Type.LONG);

    assertThat(convert(json("7"), longSchema)).isEqualTo(7L);
    assertThat(convert(json("3000000000"), longSchema)).isEqualTo(3000000000L);

    assertThatThrownBy(() -> convert(json("1.5"), longSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to long");
    assertThatThrownBy(() -> convert(json("\"7\""), longSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to long");
  }

  // ------------------------------------------------------------------
  // STRING / ENUM
  // ------------------------------------------------------------------

  @Test
  void stringIsConverted() {
    Schema stringSchema = Schema.create(Schema.Type.STRING);

    assertThat(convert(json("\"hello\""), stringSchema)).isEqualTo("hello");
    assertThat(convert(json("\"\""), stringSchema)).isEqualTo("");
  }

  @Test
  void stringFailsForNonTextualDatum() {
    assertThatThrownBy(() -> convert(json("1"), Schema.create(Schema.Type.STRING)))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to string");
  }

  @Test
  void enumIsCreatedFromTextualDatum() {
    Schema enumSchema = SchemaBuilder.enumeration("Suit").symbols("SPADES", "HEARTS");

    Object result = convert(json("\"HEARTS\""), enumSchema);

    assertThat(result).isInstanceOf(GenericData.EnumSymbol.class);
    assertThat(((GenericData.EnumSymbol) result).getSchema()).isEqualTo(enumSchema);
    assertThat(result.toString()).isEqualTo("HEARTS");
  }

  @Test
  void enumFailsForNonTextualDatum() {
    Schema enumSchema = SchemaBuilder.enumeration("Suit").symbols("SPADES", "HEARTS");

    assertThatThrownBy(() -> convert(json("0"), enumSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to string");
  }

  // ------------------------------------------------------------------
  // BYTES / FIXED
  // ------------------------------------------------------------------

  @Test
  void bytesAreWrappedInAByteBuffer() {
    byte[] payload = new byte[] {0x00, 0x01, (byte) 0xff, 0x10};

    Object result = convert(BinaryNode.valueOf(payload), Schema.create(Schema.Type.BYTES));

    assertThat(result).isInstanceOf(ByteBuffer.class);
    ByteBuffer buffer = (ByteBuffer) result;
    assertThat(buffer.remaining()).isEqualTo(4);
    byte[] read = new byte[buffer.remaining()];
    buffer.duplicate().get(read);
    assertThat(read).containsExactly(payload);
  }

  @Test
  void emptyBytesProduceAnEmptyByteBuffer() {
    Object result = convert(BinaryNode.valueOf(new byte[0]), Schema.create(Schema.Type.BYTES));

    assertThat(result).isInstanceOf(ByteBuffer.class);
    assertThat(((ByteBuffer) result).remaining()).isZero();
  }

  @Test
  void bytesFailForNonBinaryDatum() {
    assertThatThrownBy(() -> convert(json("\"AQID\""), Schema.create(Schema.Type.BYTES)))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to binary");
  }

  @Test
  void fixedRejectsBinaryDataThatIsNotShorterThanTheFixedSize() {
    // The converter guards fixed values with "bytes.length < fixedSize" and rejects the datum
    // whenever that guard does not hold, so an exactly sized payload is reported as too short.
    Schema fixedSchema = SchemaBuilder.fixed("Four").size(4);

    assertThatThrownBy(() -> convert(BinaryNode.valueOf(new byte[] {1, 2, 3, 4}), fixedSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Binary data is too short: 4 bytes");
  }

  @Test
  void fixedRejectsBinaryDataThatIsLongerThanTheFixedSize() {
    Schema fixedSchema = SchemaBuilder.fixed("Four").size(4);

    assertThatThrownBy(() -> convert(BinaryNode.valueOf(new byte[] {1, 2, 3, 4, 5}), fixedSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Binary data is too short: 5 bytes");
  }

  @Test
  void fixedWithUndersizedBinaryIsNotReportedAsATooShortDatum() {
    // This pins down the current guard: a truncated payload is not reported as a too-short
    // datum and instead fails later while the Avro fixed value is materialized.
    Schema fixedSchema = SchemaBuilder.fixed("Four").size(4);

    assertThatThrownBy(() -> convert(BinaryNode.valueOf(new byte[] {1, 2, 3}), fixedSchema))
        .isNotInstanceOf(RecordException.class);
  }

  @Test
  void fixedFailsForNonBinaryDatum() {
    Schema fixedSchema = SchemaBuilder.fixed("Four").size(4);

    assertThatThrownBy(() -> convert(json("\"AQIDBA==\""), fixedSchema))
        .isInstanceOf(RecordException.class)
        .hasMessageContaining("Cannot convert to fixed");
  }

  // ------------------------------------------------------------------
  // mixed / nested structures
  // ------------------------------------------------------------------

  @Test
  void complexNestedStructureIsConverted() {
    Schema schema = schema("{\"type\": \"record\", \"name\": \"Root\", \"fields\": ["
        + "{\"name\": \"tags\", \"type\": {\"type\": \"array\", \"items\": \"string\"}},"
        + "{\"name\": \"props\", \"type\": {\"type\": \"map\", \"values\": \"long\"}},"
        + "{\"name\": \"child\", \"type\": [\"null\", {\"type\": \"record\", \"name\": \"Child\","
        + " \"fields\": [{\"name\": \"flag\", \"type\": \"boolean\"}]}]},"
        + "{\"name\": \"maybe\", \"type\": [\"null\", \"string\"], \"default\": null}]}");

    JsonNode datum = json("{\"tags\": [\"a\", \"b\"], \"props\": {\"x\": 1, \"y\": 3000000000}, \"child\": "
        + "{\"flag\": false}}");

    GenericRecord root = (GenericRecord) convert(datum, schema);

    assertThat((List<Object>) root.get("tags")).containsExactly("a", "b");
    assertThat((Map<String, Object>) root.get("props"))
        .containsEntry("x", 1L)
        .containsEntry("y", 3000000000L);
    GenericRecord child = (GenericRecord) root.get("child");
    assertThat(child.get("flag")).isEqualTo(Boolean.FALSE);
    assertThat(root.get("maybe")).isNull();
  }

  @Test
  void conversionIsRepeatableWithTheSameModelAndSchema() {
    Schema recordSchema = SchemaBuilder.record("Rec")
        .fields()
        .name("count")
        .type()
        .intType()
        .noDefault()
        .endRecord();
    JsonNode datum = json("{\"count\": 9}");

    GenericRecord first = (GenericRecord) convert(datum, recordSchema);
    GenericRecord second = (GenericRecord) convert(datum, recordSchema);

    assertThat(first).isNotSameAs(second);
    assertThat(first.get("count")).isEqualTo(second.get("count"));
    assertThat(datum.get("count").asInt()).isEqualTo(9);
  }
}
