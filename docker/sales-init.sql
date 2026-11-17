CREATE DATABASE IF NOT EXISTS korean_sales_demo CHARACTER SET utf8mb4;
USE korean_sales_demo;
CREATE TABLE IF NOT EXISTS courses(course_id VARCHAR(8) PRIMARY KEY,name VARCHAR(100),version VARCHAR(20),price DECIMAL(12,2));
CREATE TABLE IF NOT EXISTS orders(order_id VARCHAR(32) PRIMARY KEY,course_id VARCHAR(8) NOT NULL,paid_at DATETIME NOT NULL,amount DECIMAL(12,2) NOT NULL,channel VARCHAR(30) NOT NULL,status VARCHAR(20) NOT NULL);
CREATE TABLE IF NOT EXISTS refunds(refund_id VARCHAR(32) PRIMARY KEY,order_id VARCHAR(32) NOT NULL,refunded_at DATETIME NOT NULL,amount DECIMAL(12,2) NOT NULL);
CREATE USER IF NOT EXISTS 'korean_reader'@'%' IDENTIFIED BY 'demo-reader-change-me';
GRANT SELECT ON korean_sales_demo.courses TO 'korean_reader'@'%';
GRANT SELECT ON korean_sales_demo.orders TO 'korean_reader'@'%';
GRANT SELECT ON korean_sales_demo.refunds TO 'korean_reader'@'%';
