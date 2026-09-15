package com.example.demo;

import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Marshaller;
import javax.xml.bind.annotation.XmlElement;
import javax.xml.bind.annotation.XmlRootElement;
import org.springframework.stereotype.Component;
import java.io.StringWriter;

/**
 * Exports domain objects to XML using JAXB.
 */
@Component
public class DataExporter {

    public String exportUser(String name) {
        try {
            ExportData data = new ExportData();
            data.setName(name);
            JAXBContext context = JAXBContext.newInstance(ExportData.class);
            Marshaller marshaller = context.createMarshaller();
            StringWriter writer = new StringWriter();
            marshaller.marshal(data, writer);
            return writer.toString();
        } catch (JAXBException e) {
            throw new RuntimeException("Export failed", e);
        }
    }

    @XmlRootElement
    public static class ExportData {
        private String name;

        @XmlElement
        public String getName() { return name; }
        public void setName(String name) { this.name = name; }
    }
}
