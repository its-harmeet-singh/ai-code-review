def is_even(num):
    return num % 2 == 0

def main():
    number = int(input("Enter a number: "))
    
    if is_even(number):
        print(f"{number} is Even")
    else:
        print(f"{number} is Odd")

# Run the main function
if __name__ == "__main__":
    main()
