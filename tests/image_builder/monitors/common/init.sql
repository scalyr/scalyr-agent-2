CREATE USER 'scalyr_test_user'@'localhost' IDENTIFIED BY 'scalyr_test_password';
GRANT ALL PRIVILEGES ON *.* TO 'scalyr_test_user'@'localhost';
CREATE DATABASE scalyr_test_db;